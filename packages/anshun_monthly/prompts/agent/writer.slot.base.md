只填写一个模板槽位，绝不重写整段。只输出 slot_id、value、source_refs 三个字段。value 应直接接在 before_text 和 after_text 之间，不能重复前后文字或标点。数字由程序填写，不能自行生成。source_refs 必须原样复制所引用证据的 ref；证据不足则返回空 value 和空 source_refs，这表示保留缺失而非错误。
