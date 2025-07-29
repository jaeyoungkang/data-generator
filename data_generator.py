# data_generator.py
import pandas as pd
from faker import Faker
import random
from datetime import datetime, timedelta

# LLM이 생성한 텍스트 예시는 이제 동적 모델에 맞춰 사용되므로, 
# 이 파일에서는 순수 데이터 생성 로직에 집중합니다.
fake = Faker('ko_KR')

def generate_table_data(table_name, columns, num_rows, related_data=None):
    """
    테이블 이름과 컬럼 정의에 따라 동적으로 데이터를 생성하는 범용 함수.
    실제 프로덕션에서는 이 로직이 훨씬 더 정교해야 합니다.
    이 프로토타입에서는 주요 테이블에 대한 생성 규칙을 하드코딩합니다.
    """
    data = []
    
    # 생성 규칙 정의
    for i in range(num_rows):
        row = {'id': i + 1} # 기본 id 추가
        if table_name in ['users', '고객']:
            row = {
                'user_id': i + 1,
                'name': fake.name(),
                'email': fake.email(),
                'created_at': fake.date_time_this_decade()
            }
        elif table_name in ['products', '상품']:
             row = {
                'product_id': i + 1,
                'product_name': fake.catch_phrase(),
                'description': fake.text(max_nb_chars=100),
                'price': random.randint(100, 2000) * 100,
                'category': random.choice(['의류', '가전', '식품', '도서']),
                'created_at': fake.date_time_this_decade()
            }
        elif table_name in ['orders', '주문']:
            if related_data and 'users' in related_data:
                 row = {
                    'order_id': i + 1,
                    'user_id': random.choice(related_data['users']['user_id']),
                    'order_date': fake.date_time_between(start_date='-2y', end_date='now'),
                    'status': random.choice(['completed', 'shipped', 'cancelled'])
                }
        # 필요한 다른 테이블에 대한 규칙을 여기에 추가할 수 있습니다.
        # 이 예제에서는 주요 테이블만 처리합니다.
        
        # 모델에 정의된 컬럼만 남김
        final_row = {col: row.get(col) for col in columns}
        data.append(final_row)
            
    return pd.DataFrame(data)