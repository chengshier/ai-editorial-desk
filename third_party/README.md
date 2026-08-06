# Third-party components

## MediaCrawler

MediaCrawler 已通过 Git Subtree 引入到：

```text
third_party/MediaCrawler
```

上游源码采用 squash subtree 导入；具体上游版本见 `MEDIACRAWLER_UPSTREAM.md`。

计划约束：

- 保留上游版权和许可证；
- 通过 `packages/connectors/mediacrawler_adapter` 调用；
- MVP 使用子进程隔离；
- 主系统不依赖其内部数据库和领域模型；
- 只实施已确认的五项增强与标准化风险错误输出。
