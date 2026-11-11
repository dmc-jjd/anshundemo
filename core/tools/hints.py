"""工具的技术元数据：错误码、超时、取值枚举、结果引用键。

只放"工具名 → 技术元数据"，不含任何客户业务词；执行器读这张表，不认识具体客户。
"""

#: 缺必填参数时覆盖通用错误码（保既有断言语义）
REQUIRED_ERROR_CODE = {'propose_vector_event_neighbors': 'missing_keyword_candidates'}
#: 工具超时秒数；缺省用 RunContext.timeout
TIMEOUT_S = {'propose_vector_event_neighbors': 120}
#: scope 取值枚举：tool -> 允许值
SCOPE_ENUM = {'filter_records': ('positive', 'neutral', 'negative', 'warning',
                                 'negative_warning', 'negative_or_warning', 'media')}
#: scope 不匹配时的错误码
SCOPE_ERROR_CODE = {'filter_records': 'unapproved_filter_scope'}
#: 结果引用键：tool -> (参数名, 前缀)
REF_KEY = {'filter_records': ('scope', 'filter_records:'),
           'render_chart': ('chart_type', 'render_chart:')}
#: 结果引用的简写别名：tool -> (参数名, 取值, 别名键)；workflow 读裸键，行为不变
REF_ALIAS = {'filter_records': ('scope', 'negative', 'filter_records')}
#: 必须在事实冻结（task.fact_ref 非空）后才允许执行，否则返回该错误码。
#: 这是原执行器 `historical_web_requires_frozen_writing_stage` 特判的声明化，
#: 目的不是收紧策略，而是**保住搬迁前就存在的行为**（阶段白名单只管阶段，
#: 管不到"写稿必须有冻结事实"这一条）。
REQUIRES_FROZEN_FACTS = {'search_historical_web': 'historical_web_requires_frozen_writing_stage',
                         'fetch_historical_page': 'historical_web_requires_frozen_writing_stage'}
