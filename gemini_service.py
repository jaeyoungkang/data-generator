# gemini_service.py
import os
import google.generativeai as genai
import re
import json
from dotenv import load_dotenv

load_dotenv('.env.local')


SYSTEM_PROMPT = """
당신은 데이터 모델링 전문 AI 어시스턴트입니다. 사용자의 요구사항에 맞춰 이커머스 데이터 분석을 위한 데이터 모델을 JSON 형식으로 제안하고 수정해야 합니다.

규칙:
1. 모든 데이터 모델은 반드시 테이블, 컬럼, 데이터 타입, 설명을 포함하는 JSON 형식으로 제안합니다.
2. 사용자의 피드백(예: "테이블 추가해줘", "컬럼 빼줘")을 반영하여 JSON 모델을 수정하고, 수정된 전체 JSON을 다시 제시해야 합니다.
3. 최종 모델을 제시할 때는 다른 설명 없이 JSON 데이터만 ```json ... ``` 코드 블록 안에 넣어서 반환해야 합니다.
4. 사용자가 모델을 최종 확정하면, 그 다음부터는 데이터 생성 수량을 묻는 역할로 전환됩니다.
"""

api_key = os.getenv("GEMINI_API_KEY")
model = None
if not api_key:
    print("Warning: GEMINI_API_KEY not found in .env file.")
else:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        'gemini-1.5-flash',
        system_instruction=SYSTEM_PROMPT
    )

def check_api_connection():
    if not api_key:
        return {"status": "error", "message": ".env 파일에 GEMINI_API_KEY가 없습니다."}
    try:
        genai.list_models()
        return {"status": "ok", "message": "Gemini API 연결됨"}
    except Exception as e:
        error_message = str(e)
        if "API_KEY_INVALID" in error_message:
            return {"status": "error", "message": "API 키가 유효하지 않습니다. 키를 확인해주세요."}
        return {"status": "error", "message": f"API 연결 실패: {error_message}"}

def count_tokens(contents):
    """주어진 텍스트 목록의 총 토큰 수를 계산합니다."""
    if not model:
        return {"status": "error", "message": "API model not initialized."}
    try:
        if isinstance(contents, str):
            contents = [contents]
        response = model.count_tokens(contents)
        return {"status": "ok", "total_tokens": response.total_tokens}
    except Exception as e:
        print(f"Error counting tokens: {e}")
        return {"status": "error", "message": str(e)}

def generate_content_with_usage(prompt):
    """Gemini API를 호출하고, 결과와 함께 입력/출력 토큰 사용량을 반환합니다."""
    if not model:
        return {"status": "error", "message": "API model not initialized."}
    try:
        response = model.generate_content(prompt)
        usage = response.usage_metadata
        
        # Safety-check for blocked responses
        if not response.candidates:
            return {
                "status": "blocked", 
                "text": "Safety settings blocked the response.",
                "prompt_tokens": usage.prompt_token_count if usage else 0,
                "candidates_tokens": 0,
                "total_tokens": usage.prompt_token_count if usage else 0
            }
        
        return {
            "status": "ok",
            "text": response.text,
            "prompt_tokens": usage.prompt_token_count,
            "candidates_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return {"status": "error", "message": str(e)}

def get_gemini_response_stream(chat_history):
    """Gemini API에서 응답을 스트리밍으로 받아옵니다."""
    if not model:
        yield "API 키가 설정되지 않아 응답을 생성할 수 없습니다."
        return

    messages_for_api = []
    for msg in chat_history:
        role = "user" if msg["sender"] == "user" else "model"
        messages_for_api.append({"role": role, "parts": [msg["text"]]})

    try:
        response_stream = model.generate_content(messages_for_api, stream=True)
        for chunk in response_stream:
            yield chunk.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        yield f"API 호출 중 오류가 발생했습니다: {e}"

def extract_json_from_response(text):
    match = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if match:
        json_str = match.group(1)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None
    return None
