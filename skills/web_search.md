---
name: web_search
description: Search the web using DuckDuckGo for current information
version: "1.0"
triggers:
  - "search for"
  - "look up"
  - "search the web"
  - "find online"
  - "web search"
  - "google"
enabled: true
author: system
---

# Web Search

When this skill is triggered, a web search has been performed and the results are included in the context.

## Instructions

- Review the web search results provided in `<web_search_results>` tags
- Synthesize the information into a clear, concise answer
- Cite sources when providing factual information
- If the results don't contain the needed information, let the user know
- Do not fabricate information beyond what the search results provide
