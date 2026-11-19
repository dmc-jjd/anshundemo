// 当前三家客户沿用已提供的约稿结构；在此独立维护客户与提示词的绑定。
export const CLIENTS = Object.freeze([
  { id: 'jiangchuan', name: '江川区委', promptUrl: '/static/starbridge-prompts/jiangchuan.md' },
  { id: 'wencheng', name: '文成县委', promptUrl: '/static/starbridge-prompts/wencheng.md' },
  { id: 'yanyuan', name: '盐源县委', promptUrl: '/static/starbridge-prompts/yanyuan.md' },
]);

export function buildClientDraft(clientId, topic, url, pack, prompt, clientPrompt) {
  const client = CLIENTS.find(item => item.id === clientId);
  if (!client) throw new Error('请选择约稿客户');
  if (!clientPrompt?.trim() || !prompt?.trim()) throw new Error('客户约稿提示词为空');
  if (!topic?.title?.trim()) throw new Error('请选择话题');
  return `【星桥约稿任务】\n约稿客户：${client.name}\n选定话题：${topic.title}\n来源列表：${topic.source}\n数据包链接：${url}\n【演示说明】链接所含原文、网民及媒体评论均为模拟材料，非真实舆情。\n\n${clientPrompt.trim()}\n\n${prompt.trim()}\n\n【随附数据包｜供本机链接无法访问时使用】\n${JSON.stringify(pack, null, 2)}`;
}

export async function copyDraft(text, clipboard, fallback) {
  try {
    if (!clipboard?.writeText) throw new Error('剪贴板不可用');
    await clipboard.writeText(text);
  } catch {
    if (!fallback?.(text)) throw new Error('复制失败，请允许浏览器访问剪贴板后重试');
  }
}
