# Third-party components

## MediaCrawler

MediaCrawler 将在后续步骤引入到：

```text
third_party/MediaCrawler
```

当前骨架提交不直接复制上游源码，避免在未确定同步方式前混入大量第三方历史。

计划约束：

- 保留上游版权和许可证；
- 通过 `packages/connectors/mediacrawler_adapter` 调用；
- MVP 使用子进程隔离；
- 主系统不依赖其内部数据库和领域模型；
- 只实施已确认的五项增强与标准化风险错误输出。
