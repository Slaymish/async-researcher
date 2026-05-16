# Research

Essentially the equivielnt of using claude research, but asyncronous, and using a local LLM.

## Flow

- User open kanban board
- User adds idea to backlog
- When LLM is free, it moves the idea to 'to refine' column
- LLM adds a list of open questions the user needs to answer (in ticket)
- User answers questions, when ready, user moves ticket to 'to research' column
- When LLM is free, it moves the idea to 'researching' column
- LLM does research on the idea
- LLM moves the idea to 'completed' column, with the output attached to the ticket

## Features

- Kanban board for managing research ideas`
- Async research using local LLM with a queue system
- Question generation for idea refinement
- Research execution and result storage

---

## Tech Stack

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- React Flow
- Local LLM (Ollama)

---

## Backlog

- [ ] Create Next.js project with TypeScript, Tailwind CSS, shadcn/ui, React Flow, and Local LLM (openai compatible API, URL configurable from UI)
- [ ] Implement kanban board for managing research ideas
- [ ] Implement async research using local LLM with a queue system
- [ ] Implement question generation for idea refinement
- [ ] Implement research execution and result storage
