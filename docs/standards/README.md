# 课标资料库

本地课标库收录两套国家课程标准全文，供出题和审题时核对原始要求。按年级和科目查文件请从 [课程标准索引](INDEX.md) 开始；索引列出义务教育与普通高中共 38 份文件。

## 版本与来源

| 学段 | 版本 | 官方通知 | 目录 |
| --- | --- | --- | --- |
| 义务教育（1～9 年级） | 《义务教育课程方案和课程标准（2022 年版）》 | [教材〔2022〕2号](https://hudong.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html) | `义务教育-2022/` |
| 普通高中（10～12 年级） | 《普通高中课程方案和课程标准（2017 年版 2020 年修订）》 | [教材〔2020〕3号](http://www.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html) | `普通高中-2017-2020修订/` |

课标原文的知识点标签另见 [十二年知识点标签目录](../curriculum-tags.md)。标签便于检索和组卷，不是课标原文，不能代替原文依据。

## 文件与转换说明

- Markdown 文件与源 PDF 同名，只改扩展名，按学段放在上表目录；正文保留 `## PDF 第 N 页` 页界标记，并记录源文件 SHA 与版本信息，便于追溯。
- 源 PDF 是本地资料，不提交 Git；对应 Markdown 全文和索引随项目文档维护。使用时从当前项目工作区定位 `docs/standards/`，不依赖某台机器的绝对路径。
- 义务教育 PDF 多为扫描件，Markdown 由 OCR 识别；识别文本可能在表格、公式、图示、罕见字和复杂排版处有误。引用关键条款或遇到语义异常时，按页码回查本地源 PDF。
- 普通高中 PDF 带文字层，可直接提取文本；仍需以源 PDF 对照有歧义或排版异常的片段。

## 查找方式

按索引打开对应文件，再用关键词和上下文搜索。例如从项目根目录执行：

```sh
rg -n -C 8 --glob '*.md' '一次函数|函数图象|方程' 'docs/standards/义务教育-2022/04-义务教育数学课程标准（2022年版）.md'
```

`-C 8` 会显示命中行前后文本。核对完整要求、所在章节和 `PDF 第 N 页` 标记后，引用时写 Markdown 源路径与 PDF 页码；不要只保留搜索行号，也不要把标签目录当成课标全文。

## 转换核对

网站直接读取已提交的 Markdown。维护者更新源 PDF 后，可运行 `python scripts/convert_standards.py --source-root docs/standards --output-root docs/standards` 重建；按源 SHA 和页码保存的目视校正会自动重放。完整 OCR 重建使用 Windows 简体中文／日语识别器、Python 的 `pypdf`／`pypdfium2`／`Pillow`、Poppler，以及 Node 的 [Tesseract.js](https://github.com/naptha/tesseract.js/blob/master/docs/api.md) 多语识别。Node 包不在默认模块路径时，用 `SUBJECT_HUB_TESSERACT_MODULE` 指向其目录；语言模型缓存和抽样图放在 `tmp/pdfs/` 等临时目录。

转换元数据和逐页提取状态记录在 [conversion-manifest.json](conversion-manifest.json)。在可导入 `pypdf` 的 Python 环境中，并确保本地源 PDF 可访问后，从项目根目录运行：

```sh
python scripts/verify_standards.py --report tmp/pdfs/standards-verification.json
```

脚本自动核对清单、SHA、页码结构及文字层页；它不验证 OCR 与扫描图像是否一致。已视觉确认的整页 OCR 修订记录在 [ocr-corrections.json](ocr-corrections.json)，执行状态和抽样限制见 [QA 记录](QA.md)。
