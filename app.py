# app.py
from flask import Flask, render_template, Response, stream_with_context, request, jsonify, url_for
import os
import json
import time
import glob
import gemini_service
import data_generator as dg
import dependency_analyzer as da

app = Flask(__name__)

# --- CONFIG ---
OUTPUT_DIR = "output_data"
MODELS_DIR = "models"

# --- Global State for Simplicity ---
chat_history = []

# --- ROUTES ---
@app.route('/')
def index():
    if not os.path.exists(MODELS_DIR): os.makedirs(MODELS_DIR)
    return render_template('index.html')

@app.route('/modeler')
def modeler():
    global chat_history
    chat_history = []  # Reset history when navigating to the modeler page
    return render_template('modeler.html')

@app.route('/generator')
def generator():
    model_files = [os.path.basename(f) for f in glob.glob(os.path.join(MODELS_DIR, "model_*.json"))]
    return render_template('generator.html', model_files=model_files)

@app.route('/get-model/<filename>')
def get_model(filename):
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): return jsonify({"error": "File not found"}), 404
    with open(filepath, 'r', encoding='utf-8') as f: model_data = json.load(f)
    return jsonify(model_data)

@app.route('/analyze-dependencies/<filename>')
def analyze_dependencies_route(filename):
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "모델 파일을 찾을 수 없습니다."}), 404
        
    with open(filepath, 'r', encoding='utf-8') as f:
        model_str = f.read()
        model = json.loads(model_str)

    generation_order = da.get_generation_order(model)
    if generation_order is None:
        return jsonify({"error": "모델에 순환 참조가 발견되었습니다. 모델을 수정해주세요."}), 400
    dependencies, _ = da.analyze_dependencies(model)

    llm_analysis_result = gemini_service.get_model_analysis_and_strategy(model_str)
    
    llm_analysis = ""
    if llm_analysis_result.get('status') == 'ok':
        llm_analysis = llm_analysis_result.get('analysis', "AI 분석을 생성하지 못했습니다.")
    else:
        llm_analysis = f"AI 분석 중 오류 발생: {llm_analysis_result.get('message')}"

    return jsonify({
        "generation_order": generation_order,
        "dependencies": dependencies,
        "llm_analysis": llm_analysis
    })

@app.route('/api-status')
def api_status():
    return jsonify(gemini_service.check_api_connection())

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

        # LLM의 전체 응답은 설명 텍스트와 JSON 코드 블록을 포함할 수 있습니다.
        full_response_text = ""
        for chunk in gemini_service.get_gemini_response_stream(chat_history):
            full_response_text += chunk
            # 클라이언트는 실시간으로 토큰을 받아 빠른 응답성을 체감합니다.
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
        
        chat_history.append({"sender": "llm", "text": full_response_text})
        
        # 모든 토큰 스트리밍 후, 'end_stream' 신호를 보냅니다.
        # 이 신호를 받은 클라이언트 측 JavaScript가 전체 응답 텍스트에서
        # JSON 모델을 추출하여 테이블과 그래프로 렌더링하는 작업을 수행합니다.
        yield f"data: {json.dumps({'type': 'end_stream'})}\n\n"

    return Response(stream_with_context(stream_response()), mimetype='text/event-stream')

@app.route('/save-model', methods=['POST'])
def save_model():
    model_data = request.json.get('model')
    if not model_data:
        return jsonify({"status": "error", "message": "모델 데이터가 없습니다."}), 400

    try:
        timestamp = int(time.time())
        filename = f"model_{timestamp}.json"
        filepath = os.path.join(MODELS_DIR, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(model_data, f, ensure_ascii=False, indent=4)

        success_message = f"성공적으로 모델을 **'{filename}'** 파일로 저장했습니다. 이제 [데이터 생성기 페이지]({url_for('generator')})로 이동하여 데이터를 생성할 수 있습니다."
        return jsonify({"status": "ok", "message": success_message, "filename": filename})
    except Exception as e:
        return jsonify({"status": "error", "message": f"파일 저장 중 오류 발생: {str(e)}"}), 500

# Other endpoints remain unchanged
@app.route('/estimate-tokens', methods=['POST'])
def estimate_tokens():
    data = request.json
    filename = data.get('filename')
    quantities = data.get('quantities', {})
    if not filename: return jsonify({"error": "Filename is required."}), 400
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): return jsonify({"error": "Model file not found."}), 404
    with open(filepath, 'r', encoding='utf-8') as f:
        model_str = f.read()
        model = json.loads(model_str)
    llm_analysis_result = gemini_service.get_model_analysis_and_strategy(model_str)
    model_analysis_text = llm_analysis_result.get('analysis', "") if llm_analysis_result.get('status') == 'ok' else ""
    context_prompt = f"Model Analysis:\n{model_analysis_text}\n\n" if model_analysis_text else ""
    AVG_RESPONSE_TOKENS_PER_ITEM = 10 
    total_llm_rows_for_candidates = 0
    total_estimated_prompt_tokens = 0
    for table in model.get('tables', []):
        table_name = table.get('table_name')
        num_rows = int(quantities.get(table_name, 0))
        if num_rows == 0: continue
        for column in table.get('columns', []):
            if '[LLM]' in column.get('description', ''):
                prompt = (f"{context_prompt}Generate {num_rows} examples for '{column.get('column_name')}' ({column.get('description')}). Output as JSON array.")
                result = gemini_service.count_tokens(prompt)
                if result.get('status') == 'ok':
                    total_estimated_prompt_tokens += result.get('total_tokens', 0)
                total_llm_rows_for_candidates += num_rows
    if total_estimated_prompt_tokens == 0:
        return jsonify({"estimated_prompt_tokens": 0, "estimated_candidates_tokens": 0})
    estimated_candidates_tokens = total_llm_rows_for_candidates * AVG_RESPONSE_TOKENS_PER_ITEM
    return jsonify({"estimated_prompt_tokens": total_estimated_prompt_tokens, "estimated_candidates_tokens": estimated_candidates_tokens})

@app.route('/generate-sample', methods=['POST'])
def generate_sample():
    data = request.json
    filename = data.get('filename')
    quantities = data.get('quantities', {})
    options = data.get('options', {})
    if not filename: return jsonify({"error": "Filename is required."}), 400
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): return jsonify({"error": "Model file not found."}), 404
    with open(filepath, 'r', encoding='utf-8') as f: model = json.load(f)
    generation_order = da.get_generation_order(model)
    if generation_order is None: return jsonify({"error": "Circular dependency detected."}), 400
    model_tables_map = {t['table_name']: t for t in model.get('tables', [])}
    sample_size = 5
    sample_data = {}
    generated_data_dfs = {}
    for table_name in generation_order:
        table_details = model_tables_map.get(table_name)
        if not table_details: continue
        columns_list = table_details.get("columns", [])
        num_rows = int(quantities.get(table_name, sample_size))
        df, _, _ = dg.generate_table_data(table_name, columns_list, min(num_rows, sample_size), related_data=generated_data_dfs, options=options)
        generated_data_dfs[table_name] = df
        sample_data[table_name] = json.loads(df.to_json(orient='records'))
    return jsonify(sample_data)

@app.route('/start-generation')
def start_generation():
    filename = request.args.get('filename')
    options_str = request.args.get('options', '{}')
    try: options = json.loads(options_str)
    except json.JSONDecodeError: options = {}
    if not filename: return "Error: Filename is required.", 400
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath): return "Error: Model file not found.", 404
    with open(filepath, 'r', encoding='utf-8') as f:
        model_str = f.read()
        model = json.loads(model_str)
    generation_order = da.get_generation_order(model)
    if generation_order is None:
        def error_stream(): yield log_streamer(event_type="error", data={"message": "모델에 순환 참조가 발견되었습니다."})
        return Response(stream_with_context(error_stream()), mimetype='text/event-stream')
    llm_analysis_result = gemini_service.get_model_analysis_and_strategy(model_str)
    model_analysis_text = llm_analysis_result.get('analysis', "") if llm_analysis_result.get('status') == 'ok' else ""
    model_tables_map = {t['table_name']: t for t in model.get('tables', [])}
    quantities = request.args.to_dict(flat=True)
    def log_streamer(event_type, data):
        data['type'] = event_type
        return f"data: {json.dumps(data)}\n\n"
    def generate_and_log():
        if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
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
            df, prompt_tokens, candidates_tokens = dg.generate_table_data(
                table_name, columns_list, num_rows, 
                related_data=generated_data_dfs, 
                options=options,
                model_analysis=model_analysis_text)
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
            time.sleep(0.5)
        completion_message = "✅ 모든 데이터 생성이 완료되었습니다!"
        yield log_streamer(event_type="complete", data={'message': completion_message, 'prompt_tokens': total_prompt_tokens, 'candidates_tokens': total_candidates_tokens})
    return Response(stream_with_context(generate_and_log()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
