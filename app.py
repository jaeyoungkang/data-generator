# app.py (분석 관련 개선된 부분만)
from flask import Flask, render_template, Response, stream_with_context, request, jsonify, url_for
import os
import json
import time
import glob
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import gemini_service
import data_generator as dg
import dependency_analyzer as da

app = Flask(__name__)

# --- CONFIG ---
OUTPUT_DIR = "output_data"
MODELS_DIR = "models"

# --- Global State for Simplicity ---
chat_history = []

# --- 기존 라우트들 (변경 없음) ---
@app.route('/')
def index():
    if not os.path.exists(MODELS_DIR): os.makedirs(MODELS_DIR)
    return render_template('index.html')

@app.route('/modeler')
def modeler():
    global chat_history
    chat_history = []
    return render_template('modeler.html')

@app.route('/generator')
def generator():
    model_files = [os.path.basename(f) for f in glob.glob(os.path.join(MODELS_DIR, "model_*.json"))]
    return render_template('generator.html', model_files=model_files)

@app.route('/get-model/<filename>')
def get_model(filename):
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): 
        return jsonify({"error": "File not found"}), 404
    try:
        with open(filepath, 'r', encoding='utf-8') as f: 
            model_data = json.load(f)
        return jsonify(model_data)
    except Exception as e:
        return jsonify({"error": f"파일 읽기 오류: {str(e)}"}), 500

# --- 개선된 분석 엔드포인트 ---
@app.route('/analyze-dependencies/<filename>')
def analyze_dependencies_route(filename):
    """개선된 의존성 분석 - 타임아웃과 비동기 처리"""
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "모델 파일을 찾을 수 없습니다."}), 404
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            model_str = f.read()
            model = json.loads(model_str)
    except Exception as e:
        return jsonify({"error": f"모델 파일 파싱 오류: {str(e)}"}), 400

    # 1. 빠른 규칙 기반 분석 먼저 수행
    try:
        generation_order = da.get_generation_order(model)
        if generation_order is None:
            return jsonify({"error": "모델에 순환 참조가 발견되었습니다. 모델을 수정해주세요."}), 400
        
        dependencies, _ = da.analyze_dependencies(model)
        
    except Exception as e:
        return jsonify({"error": f"의존성 분석 오류: {str(e)}"}), 500

    # 2. AI 분석을 별도 스레드에서 수행 (타임아웃 적용)
    llm_analysis = ""
    
    def run_llm_analysis():
        """AI 분석을 별도 스레드에서 실행"""
        nonlocal llm_analysis
        try:
            # 모델 크기 확인 및 제한
            if len(model_str) > 50000:  # 50KB 초과시 간소화
                simplified_model = {
                    "tables": model.get("tables", [])[:5]  # 처음 5개 테이블만
                }
                simplified_str = json.dumps(simplified_model, ensure_ascii=False)
            else:
                simplified_str = model_str
            
            llm_analysis_result = gemini_service.get_model_analysis_and_strategy(simplified_str)
            
            if llm_analysis_result.get('status') == 'ok':
                llm_analysis = llm_analysis_result.get('analysis', "")
            elif llm_analysis_result.get('status') == 'timeout':
                llm_analysis = llm_analysis_result.get('analysis', "AI 분석 시간이 초과되었습니다.")
            else:
                llm_analysis = f"AI 분석 중 오류 발생: {llm_analysis_result.get('message', 'Unknown error')}"
                
        except Exception as e:
            llm_analysis = f"AI 분석 실행 오류: {str(e)}"

    # ThreadPoolExecutor로 AI 분석 실행 (25초 타임아웃)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            future = executor.submit(run_llm_analysis)
            future.result(timeout=25)  # 25초 대기
        except FutureTimeoutError:
            llm_analysis = "**AI 분석 시간 초과**\n\n분석이 25초 내에 완료되지 않았습니다. 모델이 복잡하거나 API 응답이 지연되고 있습니다."
        except Exception as e:
            llm_analysis = f"AI 분석 스레드 오류: {str(e)}"

    # 3. 결과 반환
    return jsonify({
        "generation_order": generation_order,
        "dependencies": dependencies,
        "llm_analysis": llm_analysis if llm_analysis else "AI 분석을 수행할 수 없습니다."
    })

@app.route('/api-status')
def api_status():
    """API 상태 확인 - 타임아웃 적용"""
    try:
        # 타임아웃을 짧게 설정하여 빠른 응답
        result = gemini_service.check_api_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": f"API 상태 확인 실패: {str(e)}"
        })

@app.route('/chat', methods=['POST'])
def chat():
    global chat_history
    user_message = request.json.get('message', '')
    
    def stream_response():
        global chat_history
        if not user_message and not chat_history:
            response_text = "안녕하세요! AI 데이터 모델러입니다. 어떤 종류의 데이터 모델을 만들고 싶으신가요? (예: 온라인 쇼핑몰, 블로그, 학생 관리 시스템)"
            chat_history.append({"sender": "llm", "text": response_text})
            yield f"data: {json.dumps({'type': 'full_message', 'content': response_text})}\n\n"
            return
            
        chat_history.append({"sender": "user", "text": user_message})

        full_response_text = ""
        try:
            for chunk in gemini_service.get_gemini_response_stream(chat_history):
                full_response_text += chunk
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
            
            chat_history.append({"sender": "llm", "text": full_response_text})
            yield f"data: {json.dumps({'type': 'end_stream'})}\n\n"
            
        except Exception as e:
            error_message = f"\n\n❌ **스트림 오류**: {str(e)}\n\n페이지를 새로고침하고 다시 시도해보세요."
            yield f"data: {json.dumps({'type': 'token', 'content': error_message})}\n\n"
            yield f"data: {json.dumps({'type': 'end_stream'})}\n\n"

    return Response(stream_with_context(stream_response()), mimetype='text/event-stream')

@app.route('/save-model', methods=['POST'])
def save_model():
    model_data = request.json.get('model')
    if not model_data:
        return jsonify({"status": "error", "message": "모델 데이터가 없습니다."}), 400

    try:
        # 모델 유효성 검사
        if not isinstance(model_data, dict) or 'tables' not in model_data:
            return jsonify({"status": "error", "message": "올바르지 않은 모델 형식입니다."}), 400
        
        if not model_data['tables'] or len(model_data['tables']) == 0:
            return jsonify({"status": "error", "message": "최소 하나의 테이블이 필요합니다."}), 400

        timestamp = int(time.time())
        filename = f"model_{timestamp}.json"
        filepath = os.path.join(MODELS_DIR, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(model_data, f, ensure_ascii=False, indent=4)

        success_message = f"성공적으로 모델을 **'{filename}'** 파일로 저장했습니다. 이제 [데이터 생성기 페이지]({url_for('generator')})로 이동하여 데이터를 생성할 수 있습니다."
        return jsonify({"status": "ok", "message": success_message, "filename": filename})
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"파일 저장 중 오류 발생: {str(e)}"}), 500

@app.route('/estimate-tokens', methods=['POST'])
def estimate_tokens():
    """토큰 추정 - 타임아웃 개선"""
    data = request.json
    filename = data.get('filename')
    quantities = data.get('quantities', {})
    
    if not filename: 
        return jsonify({"error": "Filename is required."}), 400
    
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): 
        return jsonify({"error": "Model file not found."}), 404
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            model_str = f.read()
            model = json.loads(model_str)
    except Exception as e:
        return jsonify({"error": f"모델 파일 읽기 오류: {str(e)}"}), 500
    
    # 간단한 추정 방식으로 변경 (API 호출 최소화)
    try:
        AVG_RESPONSE_TOKENS_PER_ITEM = 10 
        total_llm_rows_for_candidates = 0
        total_estimated_prompt_tokens = 0
        
        for table in model.get('tables', []):
            table_name = table.get('table_name')
            num_rows = int(quantities.get(table_name, 0))
            if num_rows == 0: 
                continue
            
            for column in table.get('columns', []):
                if '[LLM]' in column.get('description', ''):
                    # 간단한 토큰 추정 (실제 API 호출 대신)
                    column_desc_length = len(column.get('description', ''))
                    estimated_prompt_tokens = (column_desc_length + 100) * 1.3  # 대략적 추정
                    total_estimated_prompt_tokens += estimated_prompt_tokens
                    total_llm_rows_for_candidates += num_rows
        
        estimated_candidates_tokens = total_llm_rows_for_candidates * AVG_RESPONSE_TOKENS_PER_ITEM
        
        return jsonify({
            "estimated_prompt_tokens": int(total_estimated_prompt_tokens), 
            "estimated_candidates_tokens": int(estimated_candidates_tokens)
        })
        
    except Exception as e:
        return jsonify({"error": f"토큰 추정 중 오류: {str(e)}"}), 500

@app.route('/generate-sample', methods=['POST'])
def generate_sample():
    """샘플 생성 - 에러 처리 개선"""
    data = request.json
    filename = data.get('filename')
    quantities = data.get('quantities', {})
    options = data.get('options', {})
    
    if not filename: 
        return jsonify({"error": "Filename is required."}), 400
    
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): 
        return jsonify({"error": "Model file not found."}), 404
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f: 
            model = json.load(f)
    except Exception as e:
        return jsonify({"error": f"모델 파일 읽기 오류: {str(e)}"}), 500
    
    try:
        generation_order = da.get_generation_order(model)
        if generation_order is None: 
            return jsonify({"error": "Circular dependency detected."}), 400
        
        model_tables_map = {t['table_name']: t for t in model.get('tables', [])}
        sample_size = 5
        sample_data = {}
        generated_data_dfs = {}
        
        for table_name in generation_order:
            table_details = model_tables_map.get(table_name)
            if not table_details: continue
            
            columns_list = table_details.get("columns", [])
            num_rows = int(quantities.get(table_name, sample_size))
            
            try:
                df, _, _ = dg.generate_table_data(
                    table_name, columns_list, min(num_rows, sample_size), 
                    related_data=generated_data_dfs, options=options
                )
                generated_data_dfs[table_name] = df
                sample_data[table_name] = json.loads(df.to_json(orient='records'))
            except Exception as e:
                # 개별 테이블 생성 실패시에도 다른 테이블은 계속 처리
                sample_data[table_name] = [{"error": f"테이블 생성 실패: {str(e)}"}]
        
        return jsonify(sample_data)
        
    except Exception as e:
        return jsonify({"error": f"샘플 생성 중 오류: {str(e)}"}), 500

@app.route('/start-generation')
def start_generation():
    """데이터 생성 - 에러 처리 및 타임아웃 개선"""
    filename = request.args.get('filename')
    options_str = request.args.get('options', '{}')
    
    try: 
        options = json.loads(options_str)
    except json.JSONDecodeError: 
        options = {}
    
    if not filename: 
        return "Error: Filename is required.", 400
    
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): 
        return "Error: Model file not found.", 404
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            model_str = f.read()
            model = json.loads(model_str)
    except Exception as e:
        def error_stream(): 
            yield log_streamer(event_type="error", data={"message": f"모델 파일 읽기 오류: {str(e)}"})
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')
    
    generation_order = da.get_generation_order(model)
    if generation_order is None:
        def error_stream(): 
            yield log_streamer(event_type="error", data={"message": "모델에 순환 참조가 발견되었습니다."})
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')
    
    # AI 분석은 선택적으로 수행 (실패해도 데이터 생성은 계속)
    model_analysis_text = ""
    try:
        llm_analysis_result = gemini_service.get_model_analysis_and_strategy(model_str)
        if llm_analysis_result.get('status') == 'ok':
            model_analysis_text = llm_analysis_result.get('analysis', "")
    except:
        pass  # AI 분석 실패해도 무시
    
    model_tables_map = {t['table_name']: t for t in model.get('tables', [])}
    quantities = request.args.to_dict(flat=True)
    
    def log_streamer(event_type, data):
        data['type'] = event_type
        return f"data: {json.dumps(data)}\n\n"
    
    def generate_and_log():
        if not os.path.exists(OUTPUT_DIR): 
            os.makedirs(OUTPUT_DIR)
        
        generated_data_dfs = {}
        total_prompt_tokens, total_candidates_tokens = 0, 0
        
        yield log_streamer(event_type="token_update", data={'prompt_tokens': 0, 'candidates_tokens': 0})
        
        for table_name in generation_order:
            table_details = model_tables_map.get(table_name)
            if not table_details: continue
            
            columns_list = table_details.get("columns", [])
            num_rows = int(quantities.get(table_name, 0))
            
            if num_rows == 0:
                yield log_streamer(event_type="log", data={'message': f"-> **{table_name}** (0개) 건너뜁니다."})
                continue
            
            yield log_streamer(event_type="log", data={'message': f"-> **{table_name}** ({num_rows}개) 생성 시작..."})
            
            try:
                df, prompt_tokens, candidates_tokens = dg.generate_table_data(
                    table_name, columns_list, num_rows, 
                    related_data=generated_data_dfs, 
                    options=options,
                    model_analysis=model_analysis_text
                )
                
                total_prompt_tokens += prompt_tokens
                total_candidates_tokens += candidates_tokens
                
                file_path = os.path.join(OUTPUT_DIR, f'{table_name}.csv')
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                generated_data_dfs[table_name] = df
                
                log_message = f"   '{table_name}.csv' 저장 완료."
                if (prompt_tokens + candidates_tokens) > 0:
                    log_message += f" (입력: {prompt_tokens}, 출력: {candidates_tokens})"
                
                yield log_streamer(event_type="log", data={'message': log_message})
                yield log_streamer(event_type="token_update", data={'prompt_tokens': total_prompt_tokens, 'candidates_tokens': total_candidates_tokens})
                
            except Exception as e:
                error_msg = f"   **{table_name}** 생성 실패: {str(e)}"
                yield log_streamer(event_type="log", data={'message': error_msg})
                # 실패해도 다음 테이블 계속 처리
            
            time.sleep(0.5)
        
        completion_message = "✅ 모든 데이터 생성이 완료되었습니다!"
        yield log_streamer(event_type="complete", data={
            'message': completion_message, 
            'prompt_tokens': total_prompt_tokens, 
            'candidates_tokens': total_candidates_tokens
        })
    
    return Response(stream_with_context(generate_and_log()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=5000)