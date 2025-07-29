# gemini_service.py
import os
import google.generativeai as genai
import re
import json
from dotenv import load_dotenv

load_dotenv('.env.local')


# --- System Prompts ---
MODELER_SYSTEM_PROMPT = """
당신은 데이터 모델링 전문 AI 어시스턴트입니다. 사용자의 요구사항에 맞춰 이커머스 데이터 분석을 위한 데이터 모델을 JSON 형식으로 제안하고 수정해야 합니다.

규칙:
1. 모든 데이터 모델은 반드시 테이블, 컬럼, 데이터 타입, 설명을 포함하는 JSON 형식으로 제안합니다.
2. 사용자의 피드백(예: "테이블 추가해줘", "컬럼 빼줘")을 반영하여 JSON 모델을 수정하고, 수정된 전체 JSON을 다시 제시해야 합니다.
3. 최종 모델을 제시할 때는 다른 설명 없이 JSON 데이터만 ```json ... ``` 코드 블록 안에 넣어서 반환해야 합니다.
4. 사용자가 모델을 최종 확정하면, 그 다음부터는 데이터 생성 수량을 묻는 역할로 전환됩니다.
"""

ANALYSIS_SYSTEM_PROMPT = """
당신은 이커머스 데이터 모델 전문 데이터 분석가입니다. 당신의 임무는 주어진 JSON 형식의 데이터 모델을 분석하고, 간결하고 통찰력 있는 데이터 생성 전략을 제안하는 것입니다.

**분석 단계:**
1.  **핵심 엔터티 식별:** 'users'(고객)나 'products'(상품)와 같이 기본적인 엔터티를 나타내는 마스터 테이블을 찾습니다.
2.  **트랜잭션/매핑 테이블 식별:** 'orders', 'order_items', 'reviews'와 같이 이벤트를 기록하거나 핵심 엔터티를 연결하는 테이블을 찾습니다.
3.  **관계 설명:** 외래 키 관계를 기반으로 이 테이블들이 어떻게 서로 연결되어 있는지 간략하게 설명합니다. (예: 'orders' 테이블은 'user'와 구매 정보를 연결합니다.)
4.  **생성 전략 제안:** 분석된 관계를 바탕으로 논리적인 데이터 생성 전략을 설명합니다. 마스터 테이블(users, products)에서 시작하여 의존성이 있는 트랜잭션 테이블로 이동하는 순서를 제안합니다. 왜 이 순서가 중요한지 설명해야 합니다. (예: "유효한 주문을 생성하려면 사용자 ID와 상품 ID가 필요하므로, 'users'와 'products' 테이블을 먼저 생성해야 합니다.")

**출력 형식:**
응답은 마크다운 형식으로 제공해주세요. 명확성을 위해 제목, 글머리 기호, 굵은 텍스트를 사용하세요.
"""


# --- API Configuration ---
api_key = os.getenv("GEMINI_API_KEY")
modeler_model = None
if not api_key:
    print("Warning: GEMINI_API_KEY not found in .env file.")
else:
    genai.configure(api_key=api_key)
    modeler_model = genai.GenerativeModel(
        'gemini-1.5-flash',
        system_instruction=MODELER_SYSTEM_PROMPT
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

def get_model_analysis_and_strategy(model_json_str):
    """Analyzes a data model using an LLM and suggests a generation strategy."""
    if not api_key:
        return {"status": "error", "message": ".env 파일에 GEMINI_API_KEY가 없습니다."}

    try:
        analysis_model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=ANALYSIS_SYSTEM_PROMPT
        )
        prompt = f"Please analyze the following e-commerce data model and propose a data generation strategy:\n\n```json\n{model_json_str}\n```"
        response = analysis_model.generate_content(prompt)
        return {"status": "ok", "analysis": response.text}
    except Exception as e:
        print(f"Error during LLM analysis: {e}")
        return {"status": "error", "message": str(e)}

def count_tokens(contents):
    """주어진 텍스트 목록의 총 토큰 수를 계산합니다."""
    if not modeler_model:
        return {"status": "error", "message": "API model not initialized."}
    try:
        if isinstance(contents, str):
            contents = [contents]
        response = modeler_model.count_tokens(contents)
        return {"status": "ok", "total_tokens": response.total_tokens}
    except Exception as e:
        print(f"Error counting tokens: {e}")
        return {"status": "error", "message": str(e)}

def generate_content_with_usage(prompt):
    """Gemini API를 호출하고, 결과와 함께 입력/출력 토큰 사용량을 반환합니다."""
    if not modeler_model:
        return {"status": "error", "message": "API model not initialized."}
    try:
        response = modeler_model.generate_content(prompt)
        usage = response.usage_metadata
        if not response.candidates:
            return {
                "status": "blocked", "text": "Safety settings blocked the response.",
                "prompt_tokens": usage.prompt_token_count if usage else 0,
                "candidates_tokens": 0,
                "total_tokens": usage.prompt_token_count if usage else 0
            }
        return {
            "status": "ok", "text": response.text,
            "prompt_tokens": usage.prompt_token_count,
            "candidates_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return {"status": "error", "message": str(e)}

def get_gemini_response_stream(chat_history):
    """Gemini API에서 응답을 스트리밍으로 받아옵니다."""
    if not modeler_model:
        yield "API 키가 설정되지 않아 응답을 생성할 수 없습니다."
        return
    messages_for_api = []
    for msg in chat_history:
        role = "user" if msg["sender"] == "user" else "model"
        messages_for_api.append({"role": role, "parts": [msg["text"]]})
    try:
        response_stream = modeler_model.generate_content(messages_for_api, stream=True)
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
