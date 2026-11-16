// canvas-editor 打包入口：产出 window.KNCanvas
// 暴露 Editor / docxPlugin / 枚举（RowFlex、TitleLevel、ListType 等），
// 页面侧只用确认过的 API，不猜命令名与枚举值。

import Editor from '@hufe921/canvas-editor'
import docxPlugin from '@hufe921/canvas-editor-plugin-docx'
import * as mod from '@hufe921/canvas-editor'

window.KNCanvas = {
  Editor,
  docxPlugin,
  RowFlex: mod.RowFlex,
  TitleLevel: mod.TitleLevel,
  ListType: mod.ListType,
  getTextFromElementList: mod.getTextFromElementList,
}

export { Editor, docxPlugin }
