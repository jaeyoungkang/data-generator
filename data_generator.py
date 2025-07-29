# data_generator.py
import pandas as pd
from faker import Faker
import random
from datetime import datetime
import gemini_service
import json
import re

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

def generate_table_data(table_name, columns_details, num_rows, related_data=None, options=None, model_analysis=""):
    """
    LLM을 사용하는 컬럼은 일괄 요청하여 효율적으로 데이터를 생성합니다.
    모델 분석 결과를 컨텍스트로 활용하여 데이터 품질을 높입니다.
    """
    if related_data is None: related_data = {}
    if options is None: options = {}
        
    total_prompt_tokens = 0
    total_candidates_tokens = 0
    
    llm_columns = [c for c in columns_details if '[LLM]' in c.get('description', '')]
    faker_columns = [c for c in columns_details if '[LLM]' not in c.get('description', '')]

    data = []
    for i in range(1, num_rows + 1):
        row = {}
        for col_detail in faker_columns:
            col_name = col_detail.get('column_name')
            if not col_name: continue
            
            pk_col = f"{table_name.rstrip('s')}_id"
            if col_name == pk_col:
                row[col_name] = i
            else:
                col_options = options.get(table_name, {}).get(col_name, {})
                row[col_name] = generate_faker_value(col_detail, table_name, related_data, col_options)
        data.append(row)

    df = pd.DataFrame(data) if data else pd.DataFrame(columns=[c['column_name'] for c in faker_columns])

    # Prepare context for LLM prompt
    context_prompt = ""
    if model_analysis:
        context_prompt = (
            "Here is an overall analysis of the data model I'm working with. "
            "Use this context to generate more realistic and consistent data.\n\n"
            f"--- Model Analysis ---\n{model_analysis}\n---------------------\n\n"
        )

    for col_detail in llm_columns:
        col_name = col_detail.get('column_name')
        col_desc = col_detail.get('description')
        
        prompt = (
            f"{context_prompt}"
            f"Based on the context above, generate {num_rows} unique and realistic examples for a column named '{col_name}' in a table. "
            f"The column's purpose is: '{col_desc}'.\n"
            "Please provide the output as a single JSON array of strings. For example: [\"value1\", \"value2\", ...]\n"
            "Do not include any other text or explanation in your response. Only the JSON array."
        )
        
        result = gemini_service.generate_content_with_usage(prompt)
        
        total_prompt_tokens += result.get('prompt_tokens', 0)
        total_candidates_tokens += result.get('candidates_tokens', 0)
        
        generated_values = []
        if result.get('status') == 'ok':
            try:
                match = re.search(r'\[.*\]', result['text'], re.DOTALL)
                if match:
                    generated_values = json.loads(match.group(0))
                else:
                    generated_values = [f"LLM_PARSE_ERROR"] * num_rows
            except json.JSONDecodeError:
                generated_values = [f"LLM_JSON_ERROR"] * num_rows
        else:
            generated_values = [f"LLM_API_ERROR: {result.get('message', 'Unknown')}" for _ in range(num_rows)]

        if len(generated_values) < num_rows:
            generated_values.extend([f"LLM_INSUFFICIENT_DATA"] * (num_rows - len(generated_values)))
        
        df[col_name] = generated_values[:num_rows]

    final_columns_order = [c.get('column_name') for c in columns_details if c.get('column_name')]
    df = df[final_columns_order]
            
    return df, total_prompt_tokens, total_candidates_tokens
