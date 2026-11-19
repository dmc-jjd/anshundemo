对输入 events 中的每个分类单元按主体和事实进行语义分类。单元可能是一条原始记录，也可能是已完成去重的事件；只判断分类，不合并、不删除记录。输入仅包含 BGE 分类头置信度不足、分类不适用或分类头不可用时需要复判的单元。
输出必须符合给定 JSON Schema：items 数组逐项覆盖输入 events 的每个 id，不遗漏、不重复；每项含 category、status、reason。status 只能是 "classified" 或 "uncertain"；reason 必须非空并说明判断依据。classified 时 category 必须是输入 categories 中的一项；不得擅自增加“其他”等未提供的类别。uncertain 时 category 留空，reason 说明具体缺少的事实或无法区分的原因。
不要因没命中关键词就 uncertain；能根据语义确定就 classified。只在现有证据仍无法确定类别时返回 uncertain，交人工研判。若收到 correction_errors，按 Schema 修正后重新完整输出。
