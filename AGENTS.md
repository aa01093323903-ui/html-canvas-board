# 给 AI 助手的说明

这个仓库是“网页画板”：用户在画布上画线框、写需求，AI 负责把它做成真正的网页或 HTML 演示稿。

## 当用户说“看一下画板 / 照画板做”

1. 读取 `board.json`，它是画板实时保存的数据，`_readme` 字段解释了所有字段。
   - `project`：宽度 `width`（px）、尺寸预设 `device`、背景色 `background`、整体说明 `notes`
   - `pages`：按顺序排列的页面，每页有 `title`、`notes`（本页说明）、`height`、`generated`（是否已生成网页）、`modules`
   - `modules`：按层级从下到上排列；`x/y/w/h` 是相对该页左上角的 px；`no` 是画布上显示的编号（全局唯一，用户会说“3 号模块”）；`inside` 是包含它的模块编号；`text` 是要原样显示的文字；`notes.content/function/effect` 是内容、功能、效果三项需求
2. 如果需要看画面：服务运行时打开 <http://localhost:5178> 截图。设计模式下每个模块左上角有编号，和 `no` 对应。
3. 用户的备注是硬性需求，要逐条实现；`text` 原样使用，不要改写。

## 生成或修改某一页的网页

每页的网页源码放在 `output/parts/<页面id>.html`，是一个 HTML 片段，不是完整文档。规则和画板内置 AI 用的一样：

- 片段会被放进 `<section data-pid="<页面id>">`，宽 `project.width`，高为该页 `height`，已经是定位容器且 `overflow:hidden`
- CSS 写在片段开头的 `<style>` 里，**每个选择器都以 `[data-pid="<页面id>"]` 开头**，不要写全局选择器
- 所有可见文字直接写在标签里，不要用 JS 生成，因为用户会在预览里直接点文字修改
- 翻到这一页时 section 会被加上 `active` class，入场动画写成 `[data-pid="…"].active .xxx { animation: … }`
- 交互脚本用 `const root=document.currentScript.closest('[data-pid]')`，只操作 root 里的元素；可点击元素用 `button` 或加 `data-nopage`，避免触发翻页

用户导入的网页也是这样的片段：原来的 `<html>`、`<body>` 变成了 `.pg-html`、`.pg-body` 两层 div，`vh/vw` 换成了 `var(--pg-vh/--pg-vw)`，按宽度的 `@media` 换成了 `@container pg`。修改导入页时保持这些写法；页面用到的图片在 `output/assets/`，用相对路径 `assets/文件名` 引用。

`output/index.html` 是画板拼好的整套页面，不要手改。用户在画板里切到“预览”或点“播放”时，会读取最新的 parts 重新拼装。

## 修改画板本身

- `index.html`：整个画板，单文件，没有构建步骤，原生 JS + CSS
- `server.py`：Python 标准库写的本地服务，负责保存数据和转发模型请求
- `config.json` 里有用户的 API Key：不要读取、打印或提交它
