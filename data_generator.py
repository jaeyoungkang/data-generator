# data_generator.py
import pandas as pd
from faker import Faker
import random
from datetime import datetime

# Faker 인스턴스 생성 (한국어)
fake = Faker('ko_KR')

def generate_single_value(column_detail, table_name, related_data, options=None):
    """
    하나의 컬럼에 대한 지능형 데이터를 생성합니다.
    [4단계 수정] 생성 우선순위 변경:
    1. 사용자 정의 옵션 -> 사용자가 지정한 규칙을 최우선으로 적용
    2. 외래 키(FK) 관계 확인 -> 부모 테이블에서 실제 ID 선택 (참조 무결성)
    3. 컬럼명 의미 추론 -> 특정 상황에 맞는 Faker 함수 사용 (의미론적 데이터)
    4. 데이터 타입 기반 -> 데이터 타입에 맞는 일반 Faker 함수 사용 (기본 생성)
    """
    if options is None:
        options = {}
        
    col_name = column_detail.get('column_name', '').lower()
    col_type = column_detail.get('data_type', '').lower()

    # 1. 사용자 정의 옵션 처리
    if options:
        # 선택 목록이 지정된 경우
        if 'list' in options and options['list']:
            return random.choice(options['list'])
        
        # 숫자 범위가 지정된 경우
        if 'min' in options and 'max' in options:
            if 'int' in col_type:
                return random.randint(int(options['min']), int(options['max']))
            else: # decimal, float 등
                return round(random.uniform(float(options['min']), float(options['max'])), 2)
        
        # 날짜 범위가 지정된 경우
        if 'startDate' in options and 'endDate' in options:
            try:
                start_dt = datetime.strptime(options['startDate'], '%Y-%m-%d')
                end_dt = datetime.strptime(options['endDate'], '%Y-%m-%d')
                return fake.date_time_between_dates(datetime_start=start_dt, datetime_end=end_dt)
            except (ValueError, TypeError):
                pass # 날짜 형식이 잘못된 경우, 아래 로직으로 넘어감

        # 특정 형식이 지정된 경우
        if 'type' in options:
            faker_type = options['type']
            if faker_type == 'name': return fake.name()
            if faker_type == 'email': return fake.email()
            if faker_type == 'address': return fake.address()
            if faker_type == 'company': return fake.company()
            if faker_type == 'phone': return fake.phone_number()

    # 2. 외래 키(FK) 참조 무결성 보장
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

    # 3. 컬럼명 기반 의미 추론
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

    # 4. 데이터 타입 기반 생성 (Fallback)
    if 'int' in col_type: return fake.random_int(min=1, max=1000)
    if 'decimal' in col_type or 'float' in col_type: return fake.pydecimal(left_digits=5, right_digits=2, positive=True)
    if 'date' in col_type or 'timestamp' in col_type: return fake.date_time_this_decade()
    if 'boolean' in col_type: return fake.boolean()
    
    return fake.word()

def generate_table_data(table_name, columns_details, num_rows, related_data=None, options=None):
    """
    테이블 이름과 컬럼 상세 정의, 사용자 옵션에 따라 동적으로 데이터를 생성하는 최종 함수.
    """
    if related_data is None: related_data = {}
    if options is None: options = {}
        
    data = []
    pk_col = f"{table_name.rstrip('s')}_id"
    table_options = options.get(table_name, {})

    for i in range(1, num_rows + 1):
        row = {}
        for col_detail in columns_details:
            col_name = col_detail.get('column_name')
            if not col_name: continue
            
            if col_name == pk_col:
                row[col_name] = i
            else:
                # [4단계 수정] 해당 컬럼의 사용자 정의 옵션을 전달
                col_options = table_options.get(col_name, {})
                row[col_name] = generate_single_value(col_detail, table_name, related_data, col_options)
        data.append(row)
            
    if not data:
        return pd.DataFrame(columns=[c.get('column_name') for c in columns_details])
        
    return pd.DataFrame(data)
