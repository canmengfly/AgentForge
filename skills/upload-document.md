---
description: Upload a document or text snippet to the personal knowledge base for future retrieval.
---

Upload content to the knowledge base (running at http://localhost:8000).

If $ARGUMENTS is a file path:
```bash
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@$ARGUMENTS" \
  -F "collection=default"
```

If $ARGUMENTS is text content, ask the user for a title then:
```bash
curl -X POST http://localhost:8000/documents/text \
  -H "Content-Type: application/json" \
  -d '{"title": "<title>", "content": "<content>", "collection": "default"}'
```

Report the returned `doc_id` to the user.
