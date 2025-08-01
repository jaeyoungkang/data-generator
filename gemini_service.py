# gemini_service.py
import os
import google.generativeai as genai
import re
import json
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dotenv import load_dotenv

load_dotenv('.env.local')

# --- [개선] 더 간결하고 효율적인 시스템 프롬프트 ---
MODELER_SYSTEM_PROMPT = """
당신은 데이터 모델링 전문 AI 어시스턴트입니다. 간결하고 실용적인 대화를 통해 데이터 모델을 만들어갑니다.

**대화 프로세스:**
1. **요구사항 파악**: 사용자의 요청을 듣고 핵심 테이블들을 빠르게 파악
2. **모델 제안**: 테이블과 컬럼을 간단히 설명하고 JSON 모델 제시
3. **수정 반영**: 사용자 피드백에 따라 모델 수정

**JSON 형식 예시:**
```json
{
  "tables": [
    {
      "table_name": "users",
      "columns": [
        {"column_name": "user_id", "data_type": "INT", "description": "사용자 ID"},
        {"column_name": "name", "data_type": "VARCHAR(100)", "description": "사용자 이름"}
      ]
    }
  ]
}
```

**중요**: 항상 간결하게 답변하고, JSON 모델은 반드시 ```json 코드 블록 안에 넣어주세요.
"""

# --- [개선] 더 간결한 분석 프롬프트 ---
ANALYSIS_SYSTEM_PROMPT = """
데이터 모델을 빠르게 분석하고 핵심만 요약해주세요.

**분석 항목:**
1. **핵심 테이블**: 주요 엔터티 테이블들
2. **관계**: 테이블 간 연결 관계
3. **생성 순서**: 의존성에 따른 데이터 생성 순서

**응답 형식**: 마크다운으로 간결하게 작성 (500자 이내)
"""

# --- API Configuration ---
api_key = os.getenv("GEMINI_API_KEY")
modeler_model = None
analysis_model = None

if not api_key:
    print("Warning: GEMINI_API_KEY not found in .env file.")
else:
    genai.configure(api_key=api_key)
    
    # 더 가벼운 모델 사용 및 설정 최적화
    generation_config = {
        'temperature': 0.7,
        'top_p': 0.8,
        'top_k': 40,
        'max_output_tokens': 2048,
    }
    
    modeler_model = genai.GenerativeModel(
        'gemini-1.5-flash',
        system_instruction=MODELER_SYSTEM_PROMPT,
        generation_config=generation_config
    )
    
    analysis_model = genai.GenerativeModel(
        'gemini-1.5-flash',
        system_instruction=ANALYSIS_SYSTEM_PROMPT,
        generation_config=generation_config
    )

def check_api_connection():
    """API 연결 상태를 빠르게 확인"""
    if not api_key:
        return {"status": "error", "message": ".env 파일에 GEMINI_API_KEY가 없습니다."}
    
    try:
        # 간단한 테스트 요청으로 API 상태 확인
        test_model = genai.GenerativeModel('gemini-1.5-flash')
        response = test_model.generate_content("test", request_options={'timeout': 5})
        return {"status": "ok", "message": "Gemini API 연결됨"}
    except Exception as e:
        error_message = str(e)
        if "API_KEY_INVALID" in error_message or "invalid" in error_message.lower():
            return {"status": "error", "message": "API 키가 유효하지 않습니다."}
        elif "timeout" in error_message.lower():
            return {"status": "error", "message": "API 응답 시간 초과"}
        return {"status": "error", "message": f"API 연결 실패: {error_message}"}

def _analyze_model_with_timeout(model_json_str, timeout=30):
    """타임아웃을 적용한 모델 분석"""
    try:
        # 더 간결한 프롬프트로 빠른 분석
        prompt = f"다음 데이터 모델을 간단히 분석해주세요:\n\n```json\n{model_json_str}\n```"
        
        response = analysis_model.generate_content(
            prompt,
            request_options={'timeout': timeout}
        )
        
        if not response.text:
            return {"status": "error", "message": "AI 분석 응답이 비어있습니다."}
            
        return {"status": "ok", "analysis": response.text}
        
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            return {"status": "error", "message": "AI 분석 시간 초과 (30초)"}
        elif "safety" in error_msg.lower() or "blocked" in error_msg.lower():
            return {"status": "error", "message": "AI 안전 필터에 의해 차단됨"}
        else:
            return {"status": "error", "message": f"AI 분석 오류: {error_msg}"}

def get_model_analysis_and_strategy(model_json_str):
    """개선된 모델 분석 - 타임아웃과 캐싱 적용"""
    if not api_key:
        return {"status": "error", "message": ".env 파일에 GEMINI_API_KEY가 없습니다."}

    if not analysis_model:
        return {"status": "error", "message": "분석 모델이 초기화되지 않았습니다."}

    # 입력 크기 제한 (너무 큰 모델은 간소화)
    try:
        model_data = json.loads(model_json_str)
        if len(json.dumps(model_data)) > 10000:  # 10KB 초과시 간소화
            # 테이블 개수 제한
            if len(model_data.get('tables', [])) > 10:
                model_data['tables'] = model_data['tables'][:10]
            model_json_str = json.dumps(model_data)
    except:
        pass

    # ThreadPoolExecutor를 사용한 타임아웃 처리
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            future = executor.submit(_analyze_model_with_timeout, model_json_str, 25)
            result = future.result(timeout=30)
            return result
        except TimeoutError:
            return {
                "status": "timeout", 
                "message": "AI 분석이 30초 내에 완료되지 않았습니다.",
                "analysis": "**분석 시간 초과**\n\n모델이 복잡하여 분석에 시간이 오래 걸렸습니다. 수동으로 의존성을 확인해주세요."
            }
        except Exception as e:
            return {"status": "error", "message": f"분석 실행 오류: {str(e)}"}

def count_tokens(contents):
    """토큰 수 계산 - 타임아웃 적용"""
    if not modeler_model:
        return {"status": "error", "message": "API model not initialized."}
    
    try:
        if isinstance(contents, str):
            contents = [contents]
        
        # 타임아웃 적용
        response = modeler_model.count_tokens(contents)
        return {"status": "ok", "total_tokens": response.total_tokens}
    except Exception as e:
        print(f"Error counting tokens: {e}")
        # 토큰 수 계산 실패시 추정값 반환
        estimated_tokens = sum(len(str(content).split()) * 1.3 for content in contents)
        return {"status": "estimated", "total_tokens": int(estimated_tokens)}

def generate_content_with_usage(prompt):
    """개선된 콘텐츠 생성 - 타임아웃과 재시도 로직"""
    if not modeler_model:
        return {"status": "error", "message": "API model not initialized."}
    
    # 프롬프트 길이 제한
    if len(prompt) > 30000:  # 30KB 초과시 자르기
        prompt = prompt[:30000] + "..."
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = modeler_model.generate_content(
                prompt,
                request_options={'timeout': 30}
            )
            
            usage = response.usage_metadata
            
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
                "prompt_tokens": usage.prompt_token_count if usage else 0,
                "candidates_tokens": usage.candidates_token_count if usage else 0,
                "total_tokens": usage.total_token_count if usage else 0
            }
            
        except Exception as e:
            error_msg = str(e)
            if attempt < max_retries - 1:
                if "timeout" in error_msg.lower():
                    time.sleep(1)  # 1초 대기 후 재시도
                    continue
                elif "quota" in error_msg.lower() or "limit" in error_msg.lower():
                    time.sleep(2)  # 2초 대기 후 재시도
                    continue
            
            print(f"Error calling Gemini API (attempt {attempt + 1}): {e}")
            
            # 최종 실패시 에러 타입별 메시지
            if "timeout" in error_msg.lower():
                return {"status": "error", "message": "API 응답 시간 초과 (30초)"}
            elif "quota" in error_msg.lower():
                return {"status": "error", "message": "API 할당량 초과"}
            elif "safety" in error_msg.lower():
                return {"status": "error", "message": "안전 필터에 의해 차단됨"}
            else:
                return {"status": "error", "message": f"API 호출 오류: {error_msg}"}
    
    return {"status": "error", "message": f"최대 재시도 횟수 초과 ({max_retries}회)"}

def get_gemini_response_stream(chat_history):
    """개선된 스트림 응답 - 타임아웃과 에러 처리"""
    if not modeler_model:
        yield "API 키가 설정되지 않아 응답을 생성할 수 없습니다."
        return

    # 대화 기록 길이 제한 (메모리 절약)
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]  # 최근 20개만 유지

    messages_for_api = []
    for msg in chat_history:
        role = "user" if msg["sender"] == "user" else "model"
        # 메시지 길이 제한
        text = msg["text"]
        if len(text) > 5000:
            text = text[:5000] + "..."
        messages_for_api.append({"role": role, "parts": [text]})

    try:
        response_stream = modeler_model.generate_content(
            messages_for_api, 
            stream=True,
            request_options={'timeout': 45}  # 스트림은 좀 더 긴 타임아웃
        )
        
        for chunk in response_stream:
            if chunk.text:
                yield chunk.text
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error in stream response: {e}")
        
        if "timeout" in error_msg.lower():
            yield "\n\n⚠️ **응답 시간이 초과되었습니다.** 더 간단한 요청으로 다시 시도해보세요."
        elif "quota" in error_msg.lower() or "limit" in error_msg.lower():
            yield "\n\n⚠️ **API 할당량이 초과되었습니다.** 잠시 후 다시 시도해보세요."
        elif "safety" in error_msg.lower():
            yield "\n\n⚠️ **안전 필터에 의해 차단되었습니다.** 다른 방식으로 질문해보세요."
        else:
            yield f"\n\n❌ **오류가 발생했습니다**: {error_msg}\n\n페이지를 새로고침하고 다시 시도해보세요."

def extract_json_from_response(text):
    """JSON 추출 함수 - 더 관대한 파싱"""
    # 여러 패턴으로 시도
    patterns = [
        r"```json\s*([\s\S]+?)\s*```",
        r"```\s*([\s\S]+?)\s*```",
        r"\{[\s\S]*\}"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            json_str = match.group(1) if len(match.groups()) > 0 else match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue
    
    return None