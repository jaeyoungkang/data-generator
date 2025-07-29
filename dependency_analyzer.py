# dependency_analyzer.py
from collections import defaultdict

def analyze_dependencies(model):
    """
    데이터 모델을 분석하여 테이블 간의 의존성 그래프를 생성합니다.
    'xxx_id' 형식의 컬럼명을 외래 키로 간주하여 관계를 파악합니다.

    Args:
        model (dict): 데이터 모델 JSON 객체

    Returns:
        dict: 테이블 이름을 키로, 해당 테이블이 의존하는 테이블 리스트를 값으로 갖는 의존성 맵
        dict: 테이블 이름을 키로, 해당 테이블을 참조하는 테이블 리스트를 값으로 갖는 역의존성 맵
    """
    dependencies = defaultdict(list)
    reverse_dependencies = defaultdict(list)
    
    tables = model.get('tables', [])
    table_names = [table.get('table_name') for table in tables if table.get('table_name')]

    for table_details in tables:
        source_table = table_details.get('table_name')
        if not source_table:
            continue

        columns = table_details.get('columns', [])
        for column in columns:
            col_name = column.get('column_name', '')
            
            # 외래 키 명명 규칙 (xxx_id) 확인
            if col_name.endswith('_id'):
                # 자기 자신을 참조하는 기본 키(PK)는 제외 (e.g., users.user_id)
                pk_candidate1 = f"{source_table}_id"
                pk_candidate2 = f"{source_table.rstrip('s')}_id" # 단수형 테이블 이름도 고려 (e.g., user_id for users table)
                if col_name == pk_candidate1 or col_name == pk_candidate2:
                    continue

                # 외래 키가 참조하는 테이블 이름 추론
                target_table_prefix = col_name.replace('_id', '')
                
                # 모델에 존재하는 테이블 중에서 참조 대상 찾기 (복수형/단수형 모두 고려)
                target_table = None
                if f"{target_table_prefix}s" in table_names:
                    target_table = f"{target_table_prefix}s"
                elif target_table_prefix in table_names:
                    target_table = target_table_prefix
                
                if target_table and source_table != target_table:
                    # 의존성 관계 기록 (source_table이 target_table에 의존)
                    if target_table not in dependencies[source_table]:
                        dependencies[source_table].append(target_table)
                    if source_table not in reverse_dependencies[target_table]:
                        reverse_dependencies[target_table].append(source_table)

    return dict(dependencies), dict(reverse_dependencies)


def get_generation_order(model):
    """
    의존성 분석 결과를 바탕으로 위상 정렬(Topological Sort)을 수행하여,
    데이터를 생성해야 할 올바른 테이블 순서를 반환합니다.

    Args:
        model (dict): 데이터 모델 JSON 객체

    Returns:
        list: 데이터 생성 순서에 맞게 정렬된 테이블 이름 리스트
        None: 순환 참조가 발견되어 정렬이 불가능한 경우
    """
    dependencies, _ = analyze_dependencies(model)
    
    # 모든 테이블 목록
    all_tables = [table.get('table_name') for table in model.get('tables', []) if table.get('table_name')]
    
    # 각 테이블의 진입 차수(in-degree) 계산
    in_degree = {table: 0 for table in all_tables}
    for table in dependencies:
        for dep_table in dependencies[table]:
            in_degree[table] += 1

    # 진입 차수가 0인 테이블을 큐에 추가
    queue = [table for table in all_tables if in_degree[table] == 0]
    
    sorted_order = []
    
    while queue:
        current_table = queue.pop(0)
        sorted_order.append(current_table)
        
        # 현재 테이블을 참조하는 다른 테이블들의 진입 차수 감소
        for table in all_tables:
            if current_table in dependencies.get(table, []):
                in_degree[table] -= 1
                if in_degree[table] == 0:
                    queue.append(table)

    # 모든 테이블이 정렬되었는지 확인 (순환 참조 감지)
    if len(sorted_order) == len(all_tables):
        return sorted_order
    else:
        # 순환 참조가 있어 정렬이 불가능한 경우
        return None
