---
description: Search the personal knowledge base for relevant documents and context. Use before answering questions that require domain-specific knowledge.
---

Search the knowledge base (running at http://localhost:8000) for: $ARGUMENTS

Call POST http://localhost:8000/search with:
```json
{
  "query": "<derived from $ARGUMENTS>",
  "collection": "default",
  "top_k": 5
}
```

Incorporate the top-scoring hits into your answer. Cite the `title` from each hit's metadata.
