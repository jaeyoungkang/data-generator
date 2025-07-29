# models.py

# 데이터 모델 정의
DATA_MODEL = {
    'users': {
        'columns': ['user_id', 'name', 'email', 'created_at'],
        'description': '고객 정보 테이블'
    },
    'products': {
        'columns': ['product_id', 'product_name', 'description', 'price', 'category', 'created_at'],
        'description': '상품 정보 테이블'
    },
    'orders': {
        'columns': ['order_id', 'user_id', 'order_date', 'status'],
        'description': '주문 기본 정보 테이블'
    },
    'order_items': {
        'columns': ['order_item_id', 'order_id', 'product_id', 'quantity', 'price_per_unit'],
        'description': '주문 상세 내역 테이블'
    },
    'reviews': {
        'columns': ['review_id', 'user_id', 'product_id', 'rating', 'comment', 'created_at'],
        'description': '상품 리뷰 테이블'
    }
}

# LLM 생성 텍스트 데이터 명세 (시뮬레이션)
LLM_GENERATED_PRODUCTS = {
    '의류': [
        {"name": "컴포트핏 데일리 후드티", "desc": "부드러운 기모 안감으로 제작되어 어떤 날씨에도 따뜻함을 선사하는 오버사이즈 후드티입니다."},
        {"name": "쿨링 기능성 트레이닝 팬츠", "desc": "땀을 빠르게 흡수하고 건조시키는 기능성 원단으로 제작되어 운동 시 최적의 편안함을 제공합니다."},
        {"name": "클래식 린넨 셔츠", "desc": "통기성이 뛰어난 100% 린넨 소재로 만들어져 여름철에도 시원하고 스타일리시하게 착용할 수 있습니다."},
    ],
    '가전': [
        {"name": "AI 스마트 공기청정기 Pro", "desc": "초미세먼지를 99.9% 제거하며, AI가 실내 공기질을 분석하여 자동으로 운전 모드를 조절합니다."},
        {"name": "노이즈 캔슬링 무선 이어폰", "desc": "주변 소음을 완벽하게 차단하여 몰입감 있는 사운드를 경험하게 해주는 고성능 무선 이어폰입니다."},
        {"name": "올인원 스팀 에어프라이어", "desc": "튀김, 구이, 찜 요리까지 가능한 만능 주방 가전. 스팀 기능으로 더욱 촉촉한 요리를 즐겨보세요."},
    ],
    '식품': [
        {"name": "유기농 무항생제 신선 달걀 (10구)", "desc": "자연 방사 환경에서 자란 건강한 닭이 낳은 신선하고 고소한 유기농 달걀입니다."},
        {"name": "산지직송 GAP 인증 사과 5kg", "desc": "풍부한 과즙과 아삭한 식감이 일품인 고당도 GAP 인증 사과를 집에서 편하게 받아보세요."},
        {"name": "1등급 한우 등심 스테이크 (300g)", "desc": "마블링이 풍부하여 입안에서 녹는 듯한 부드러움을 자랑하는 최고급 한우 등심입니다."},
    ]
}

LLM_GENERATED_REVIEWS = {
    # 긍정 (70%)
    'positive': [
        "배송도 빠르고 제품 품질도 기대 이상입니다! 정말 만족스러워요.",
        "디자인이 너무 예쁘고 마감도 훌륭하네요. 강력 추천합니다.",
        "사용하기 편리하고 성능이 좋습니다. 다음에도 이 브랜드 제품을 구매할 것 같아요.",
    ],
    # 부정 (20%)
    'negative': [
        "생각보다 품질이 별로네요. 실망스럽습니다.",
        "포장이 훼손된 채로 배송되었습니다. 기분이 좋지 않네요.",
        "설명서가 너무 부실해서 사용법을 알기 어렵습니다.",
    ],
    # 중립 (10%)
    'neutral': [
        "그냥 평범한 제품입니다. 나쁘지 않아요.",
        "가격만큼 하는 것 같습니다.",
        "아직 사용 전이라 잘 모르겠습니다.",
    ]
}