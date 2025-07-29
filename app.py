# app.py
from flask import Flask, render_template, Response, stream_with_context, request, jsonify, url_for
import os
import json
import time
import glob # 파일 목록 조회를 위해 glob 라이브러리 추가
import gemini_service
import data_generator as dg

app = Flask(__name__)

# --- CONFIG & STATE ---
OUTPUT_DIR = "output_data"
# [수정] 모델 저장 경로를 'models' 폴더로 변경
MODELS_DIR = "models" 
conversation_state = {}

def reset_modeler_state():
    global conversation_state
    conversation_state = {
        "step": "MODEL_CONVERSATION", "chat_history": [], "confirmed_model": None,
    }

# --- ROUTES ---
@app.route('/')
def index():
    # 애플리케이션 시작 시 models 폴더가 없으면 생성
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)
    return render_template('index.html')

@app.route('/modeler')
def modeler():
    reset_modeler_state()
    return render_template('modeler.html')

# [수정] /generator 라우트가 모델 목록을 전달하도록 변경
@app.route('/generator')
def generator():
    # models 폴더에서 model_*.json 파일 목록을 찾음
    model_files = [os.path.basename(f) for f in glob.glob(os.path.join(MODELS_DIR, "model_*.json"))]
    return render_template('generator.html', model_files=model_files)

# [신규] 선택된 모델 파일의 내용을 JSON으로 반환하는 API
@app.route('/get-model/<filename>')
def get_model(filename):
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    
    with open(filepath, 'r', encoding='utf-8') as f:
        model_data = json.load(f)
    return jsonify(model_data)


@app.route('/api-status')
def api_status():
    status = gemini_service.check_api_connection()
    return jsonify(status)

# [수정] 모델 확정 시 동적 파일명으로 저장
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')
    
    def stream_response():
        global conversation_state
        # ... (첫 인사 및 대화 스트리밍 로직은 이전과 동일) ...
        if not user_message and not conversation_state["chat_history"]:
            response_text = "안녕하세요! AI 데이터 모델러입니다. 이커머스 분석을 위한 데이터 모델 설계를 시작해볼까요?"
            conversation_state["chat_history"].append({"sender": "llm", "text": response_text})
            yield f"data: {json.dumps({'type': 'full_message', 'content': response_text})}\n\n"
            return
            
        conversation_state["chat_history"].append({"sender": "user", "text": user_message})

        if conversation_state["step"] == "MODEL_CONVERSATION":
            full_response_text = ""
            for chunk in gemini_service.get_gemini_response_stream(conversation_state["chat_history"]):
                full_response_text += chunk
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
            
            conversation_state["chat_history"].append({"sender": "llm", "text": full_response_text})
            potential_model = gemini_service.extract_json_from_response(full_response_text)
            if potential_model:
                conversation_state["confirmed_model"] = potential_model

            if any(keyword in user_message for keyword in ["확정", "결정", "그걸로 해줘", "좋아"]):
                if conversation_state["confirmed_model"]:
                    # [수정] 타임스탬프를 이용해 고유한 파일명 생성
                    timestamp = int(time.time())
                    filename = f"model_{timestamp}.json"
                    filepath = os.path.join(MODELS_DIR, filename)
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(conversation_state["confirmed_model"], f, ensure_ascii=False, indent=4)
                    
                    next_step_message = f"좋습니다! 데이터 모델이 **'{filename}'** 파일로 저장되었습니다.\n\n이제 [데이터 생성기 페이지]({url_for('generator')})로 이동하여 방금 만든 모델을 선택하고 더미 데이터를 생성할 수 있습니다."
                    yield f"data: {json.dumps({'type': 'full_message', 'content': next_step_message})}\n\n"
                    reset_modeler_state()

        yield f"data: {json.dumps({'type': 'end_stream'})}\n\n"
    return Response(stream_with_context(stream_response()), mimetype='text/event-stream')


# [수정] 샘플/전체 데이터 생성 시 선택된 모델 파일명을 받도록 변경
@app.route('/generate-sample', methods=['POST'])
def generate_sample():
    data = request.json
    filename = data.get('filename')
    quantities = data.get('quantities', {})
    
    if not filename:
        return jsonify({"error": "Filename is required."}), 400
        
    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Model file not found."}), 404

    with open(filepath, 'r', encoding='utf-8') as f:
        model = json.load(f)
    
    sample_size = 5
    sample_htmls = {}
    generated_data_dfs = {}

    for table_name, table_details in model.items():
        num_rows = int(quantities.get(table_name, sample_size))
        df = dg.generate_table_data(table_name, table_details.get("columns", []), min(num_rows, sample_size), related_data=generated_data_dfs)
        generated_data_dfs[table_name] = df
        sample_htmls[table_name] = df.to_html(classes='table table-striped table-sm', index=False, border=0)
        
    return jsonify(sample_htmls)

@app.route('/start-generation')
def start_generation():
    filename = request.args.get('filename')
    if not filename:
        return "Error: Filename is required.", 400

    filepath = os.path.join(MODELS_DIR, filename)
    if not os.path.exists(filepath):
        return "Error: Model file not found.", 404
    
    with open(filepath, 'r', encoding='utf-8') as f:
        model = json.load(f)
    
    quantities = request.args.to_dict(flat=True)
    
    def generate_and_log():
        if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
        generated_data_dfs = {}
        for table_name, table_details in model.items():
            num_rows = int(quantities.get(table_name, 0))
            yield log_streamer(f"-> **{table_name}** ({num_rows}개) 생성 시작...")
            df = dg.generate_table_data(table_name, table_details.get("columns", []), num_rows, related_data=generated_data_dfs)
            file_path = os.path.join(OUTPUT_DIR, f'{table_name}.csv')
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
            generated_data_dfs[table_name] = df
            yield log_streamer(f"   '{table_name}.csv' 저장 완료.")
            time.sleep(0.5)
        yield log_streamer(f"✅ 모든 데이터 생성이 완료되었습니다!", event_type="complete")

    def log_streamer(message, event_type="log"):
        return f"data: {json.dumps({'type': event_type, 'message': message})}\n\n"

    return Response(stream_with_context(generate_and_log()), mimetype='text/event-stream')


if __name__ == '__main__':
    app.run(debug=True, port=5000)