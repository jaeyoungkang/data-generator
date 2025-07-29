# gemini_service.py
import os
import google.generativeai as genai
import re
import json
from dotenv import load_dotenv

load_dotenv('.env.local')


# --- [수정] 시각적 UX를 위한 시스템 프롬프트 ---
MODELER_SYSTEM_PROMPT = """
당신은 데이터 모델링 전문 AI 어시스턴트입니다. 당신의 목표는 사용자와 단계별로 소통하며 최적의 데이터 모델을 함께 만들어가는 것입니다.

**대화 프로세스:**

**1단계: 요구사항 이해 및 의견 제시**
* 사용자의 초기 요청을 접수하고, 일반적인 베스트 프랙티스나 추가하면 좋을 만한 사항에 대해 먼저 의견을 제시합니다. (예: "좋습니다. 기본적인 사용자, 상품, 주문 정보 외에도, 고객 리뷰 데이터를 추가하면 나중에 유용한 분석을 할 수 있습니다. 리뷰 테이블도 함께 구성해드릴까요?")
* 사용자의 답변을 기다립니다.

**2단계: 모델 초안 제안 및 설명**
* 사용자의 확인을 받으면, 논의된 내용을 바탕으로 데이터 모델의 초안에 대해 **테이블 형식으로 설명**합니다. 각 테이블의 역할과 컬럼에 대해 설명하고, 테이블 간의 관계(예: 'orders' 테이블의 'user_id'는 'users' 테이블을 참조합니다)를 명확히 언급해주세요.
* 설명과 함께, 전체 데이터 모델이 담긴 `json` 코드 블록을 **반드시** 제공해야 합니다. 이 JSON은 화면에 테이블과 관계도를 그리는 데 사용됩니다.

**3단계: 수정 및 개선**
* 사용자가 모델을 보고 수정사항을 요청하면, 이를 반영하여 수정된 설명과 **수정된 전체 JSON 모델**을 다시 제시합니다.

**4단계: 최종 확인 유도**
* 모델이 완성되었다고 판단되면, 사용자에게 최종 확인을 요청합니다. (예: "이 모델로 확정할까요? 더 수정할 부분이 없다면 아래 '모델로 확정' 버튼을 눌러 저장해주세요.")

**중요 규칙:**
* 사용자가 요청한 내용을 시각적으로 명확하게 파악할 수 있도록, **설명은 테이블 구조 중심으로** 해주세요.
* JSON 데이터는 설명을 위한 보조 자료이므로, 설명 텍스트에서 JSON 구문을 직접 언급하지 마세요.
* JSON 모델을 제시할 때는 반드시 ```json ... ``` 코드 블록 안에 넣어서 반환해야 합니다.
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
