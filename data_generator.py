# data_generator.py
import pandas as pd
from faker import Faker
import random
from datetime import datetime
import gemini_service
import json
import re
import time

# Faker 인스턴스 생성 (한국어)
fake = Faker('ko_KR')

def generate_faker_value(column_detail, table_name, related_data, options=None):
    """
    Faker 또는 규칙 기반으로 단일 값을 생성합니다. (LLM 호출 로직 제외)
    """
    if options is None: options = {}
    col_name = column_detail.get('column_name', '').lower()
    col_type = column_detail.get('data_type', '').lower()

    if options:
        if 'list' in options and options['list']:
            return random.choice(options['list'])
        if 'min' in options and 'max' in options:
            if 'int' in col_type:
                return random.randint(int(options['min']), int(options['max']))
            else:
                return round(random.uniform(float(options['min']), float(options['max'])), 2)
        if 'startDate' in options and 'endDate' in options:
            try:
                start_dt = datetime.strptime(options['startDate'], '%Y-%m-%d')
                end_dt = datetime.strptime(options['endDate'], '%Y-%m-%d')
                return fake.date_time_between_dates(datetime_start=start_dt, datetime_end=end_dt)
            except (ValueError, TypeError):
                pass
        if 'type' in options:
            faker_type = options['type']
            if faker_type == 'name': return fake.name()
            if faker_type == 'email': return fake.email()
            if faker_type == 'address': return fake.address()
            if faker_type == 'company': return fake.company()
            if faker_type == 'phone': return fake.phone_number()

    if col_name.endswith('_id'):
        pk_candidate1 = f"{table_name}_id"
        pk_candidate2 = f"{table_name.rstrip('s')}_id"
        if col_name != pk_candidate1 and col_name != pk_candidate2:
            parent_table_prefix = col_name.replace('_id', '')
            parent_df = related_data.get(f"{parent_table_prefix}s")
            if parent_df is None: parent_df = related_data.get(parent_table_prefix)
            if parent_df is not None and not parent_df.empty:
                parent_pk_col = f"{parent_table_prefix}_id"
                if parent_pk_col in parent_df.columns:
                    return random.choice(parent_df[parent_pk_col].tolist())

    if 'name' in col_name or '이름' in col_name: return fake.name()
    if 'email' in col_name: return fake.email()
    if 'address' in col_name or '주소' in col_name: return fake.address()
    if 'phone' in col_name or '전화' in col_name: return fake.phone_number()
    if 'company' in col_name or '회사' in col_name: return fake.company()
    if 'title' in col_name or '제목' in col_name: return fake.catch_phrase()
    if 'description' in col_name or 'comment' in col_name or '내용' in col_name: return fake.text(max_nb_chars=100)
    if 'status' in col_name: return random.choice(['completed', 'shipped', 'pending', 'cancelled'])
    if 'category' in col_name: return random.choice(['의류', '가전', '식품', '도서', '스포츠'])
    if 'price' in col_name or 'amount' in col_name: return random.randint(100, 5000) * 100
    if 'quantity' in col_name or '수량' in col_name: return random.randint(1, 10)
    if 'rating' in col_name or '평점' in col_name: return random.randint(1, 5)
    if 'date' in col_name or 'timestamp' in col_type or '_at' in col_name: return fake.date_time_between(start_date='-2y', end_date='now')

    if 'int' in col_type: return fake.random_int(min=1, max=1000)
    if 'decimal' in col_type or 'float' in col_type: return fake.pydecimal(left_digits=5, right_digits=2, positive=True)
    if 'date' in col_type or 'timestamp' in col_type: return fake.date_time_this_decade()
    if 'boolean' in col_type: return fake.boolean()
    
    return fake.word()

def generate_llm_data_with_fallback(col_detail, num_rows, model_analysis="", max_retries=2):
    """
    LLM을 사용하여 데이터를 생성하되, 실패시 Faker로 대체하는 함수
    """
    col_name = col_detail.get('column_name')
    col_desc = col_detail.get('description', '')
    
    # 간단한 프롬프트로 빠른 생성
    context_prompt = ""
    if model_analysis and len(model_analysis) < 1000:  # 컨텍스트가 너무 길지 않을 때만 사용
        context_prompt = f"Context: {model_analysis[:500]}...\n\n"
    
    prompt = (
        f"{context_prompt}"
        f"Generate {num_rows} realistic examples for column '{col_name}': {col_desc}\n"
        f"Return only a JSON array like: [\"value1\", \"value2\", ...]\n"
        f"No explanations, just the array."
    )
    
    for attempt in range(max_retries):
        try:
            result = gemini_service.generate_content_with_usage(prompt)
            
            if result.get('status') == 'ok' and result.get('text'):
                # JSON 추출 시도
                text = result['text'].strip()
                
                # 여러 패턴으로 JSON 추출 시도
                json_patterns = [
                    r'\[.*?\]',  # 기본 배열 패턴
                    r'```json\s*(\[.*?\])\s*```',  # 코드 블록 내 배열
                    r'```\s*(\[.*?\])\s*```',  # 코드 블록 (json 태그 없음)
                ]
                
                parsed_values = None
                for pattern in json_patterns:
                    match = re.search(pattern, text, re.DOTALL)
                    if match:
                        json_str = match.group(1) if match.groups() else match.group(0)
                        try:
                            parsed_values = json.loads(json_str)
                            if isinstance(parsed_values, list) and len(parsed_values) > 0:
                                break
                        except json.JSONDecodeError:
                            continue
                
                if parsed_values and len(parsed_values) >= num_rows:
                    return (
                        parsed_values[:num_rows], 
                        result.get('prompt_tokens', 0), 
                        result.get('candidates_tokens', 0)
                    )
                elif parsed_values and len(parsed_values) > 0:
                    # 부족한 개수는 반복으로 채우기
                    while len(parsed_values) < num_rows:
                        parsed_values.extend(parsed_values[:min(len(parsed_values), num_rows - len(parsed_values))])
                    return (
                        parsed_values[:num_rows], 
                        result.get('prompt_tokens', 0), 
                        result.get('candidates_tokens', 0)
                    )
                    
            # LLM 응답이 없거나 파싱 실패시 재시도
            if attempt < max_retries - 1:
                time.sleep(1)  # 1초 대기 후 재시도
                continue
                
        except Exception as e:
            print(f"LLM 생성 시도 {attempt + 1} 실패: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2)  # 2초 대기 후 재시도
                continue
    
    # 모든 시도 실패시 Faker로 대체
    print(f"LLM 생성 실패, Faker로 대체: {col_name}")
    fallback_values = []
    for _ in range(num_rows):
        fallback_value = generate_faker_value(col_detail, "fallback_table", {}, {})
        fallback_values.append(str(fallback_value))
    
    return fallback_values, 0, 0  # 토큰 사용량 0

def generate_table_data(table_name, columns_details, num_rows, related_data=None, options=None, model_analysis=""):
    """
    개선된 테이블 데이터 생성 - LLM 실패시 안정적 대체
    """
    if related_data is None: related_data = {}
    if options is None: options = {}
        
    total_prompt_tokens = 0
    total_candidates_tokens = 0
    
    # 컬럼을 LLM/Faker로 분류
    llm_columns = [c for c in columns_details if '[LLM]' in c.get('description', '')]
    faker_columns = [c for c in columns_details if '[LLM]' not in c.get('description', '')]

    # 1. Faker 기반 컬럼 먼저 생성 (빠른 처리)
    data = []
    for i in range(1, num_rows + 1):
        row = {}
        for col_detail in faker_columns:
            col_name = col_detail.get('column_name')
            if not col_name: continue
            
            # 기본 키 처리
            pk_col = f"{table_name.rstrip('s')}_id"
            if col_name == pk_col:
                row[col_name] = i
            else:
                col_options = options.get(table_name, {}).get(col_name, {})
                try:
                    row[col_name] = generate_faker_value(col_detail, table_name, related_data, col_options)
                except Exception as e:
                    print(f"Faker 생성 실패 ({col_name}): {str(e)}")
                    row[col_name] = f"ERROR_{i}"
        data.append(row)

    df = pd.DataFrame(data) if data else pd.DataFrame(columns=[c['column_name'] for c in faker_columns])

    # 2. LLM 기반 컬럼 생성 (안정적 처리)
    for col_detail in llm_columns:
        col_name = col_detail.get('column_name')
        if not col_name: continue
        
        print(f"LLM 컬럼 생성 중: {col_name}")
        
        try:
            generated_values, prompt_tokens, candidates_tokens = generate_llm_data_with_fallback(
                col_detail, num_rows, model_analysis
            )
            
            total_prompt_tokens += prompt_tokens
            total_candidates_tokens += candidates_tokens
            
            # 생성된 값들을 DataFrame에 추가
            if len(generated_values) == num_rows:
                df[col_name] = generated_values
            else:
                # 길이가 맞지 않을 때 조정
                if len(generated_values) > num_rows:
                    df[col_name] = generated_values[:num_rows]
                else:
                    # 부족한 경우 반복으로 채우기
                    extended_values = generated_values[:]
                    while len(extended_values) < num_rows:
                        extended_values.extend(generated_values[:min(len(generated_values), num_rows - len(extended_values))])
                    df[col_name] = extended_values[:num_rows]
            
        except Exception as e:
            print(f"LLM 컬럼 생성 완전 실패 ({col_name}): {str(e)}")
            # 최후의 수단: 간단한 더미 값
            df[col_name] = [f"LLM_FALLBACK_{i+1}" for i in range(num_rows)]

    # 3. 최종 컬럼 순서 정리
    final_columns_order = [c.get('column_name') for c in columns_details if c.get('column_name')]
    existing_columns = [col for col in final_columns_order if col in df.columns]
    
    if existing_columns:
        df = df[existing_columns]
    else:
        # 컬럼이 하나도 없는 경우 빈 DataFrame 반환
        df = pd.DataFrame()
            
    return df, total_prompt_tokens, total_candidates_tokens