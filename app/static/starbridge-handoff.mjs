export const HANDOFF_KEY = 'kn-starbridge-draft-v1';

export function buildDraft(topic, url, pack, prompt) {
  return `【星桥约稿任务】\n选定话题：${topic.title}\n来源列表：${topic.source}\n数据包链接：${url}\n【演示说明】链接所含原文、网民及媒体评论均为模拟材料，非真实舆情。\n\n${prompt.trim()}\n\n【随附数据包｜供本机链接无法访问时使用】\n${JSON.stringify(pack, null, 2)}`;
}

// 返回 false 表示组件还未就绪；保留交接内容供下一次渲染重试。
export function applyHandoff(chat, storage) {
  const raw = storage.getItem(HANDOFF_KEY);
  if (!raw) return false;
  const draft = JSON.parse(raw);
  if (draft.version !== 1 || typeof draft.text !== 'string' || !draft.text.trim()) {
    throw new Error('星桥待发送内容格式无效，请返回工作台重新选择。');
  }
  const input = chat.shadowRoot?.querySelector('[contenteditable="true"][role="textbox"]');
  if (!input) return false;
  const previous = input.innerText || '';
  input.innerText = previous.trim() ? previous + '\n\n' + draft.text : draft.text;
  input.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
  storage.removeItem(HANDOFF_KEY);
  input.focus();
  return true;
}
