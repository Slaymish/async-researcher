"use client";

import { useState, useEffect, useCallback } from "react";
import type { Ticket, ColumnId, Question } from "@/types";

const STORAGE_KEY = "researcher-kanban";

function generateId() {
  return Math.random().toString(36).slice(2, 11);
}

function loadTickets(): Ticket[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveTickets(tickets: Ticket[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tickets));
}

export function useKanban() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const stored = loadTickets();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTickets(stored);
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded) saveTickets(tickets);
  }, [tickets, loaded]);

  const addTicket = useCallback((title: string, description: string) => {
    const now = new Date().toISOString();
    const ticket: Ticket = {
      id: generateId(),
      title,
      description,
      columnId: "backlog",
      questions: [],
      createdAt: now,
      updatedAt: now,
    };
    setTickets((prev) => [...prev, ticket]);
    return ticket;
  }, []);

  const updateTicket = useCallback((id: string, updates: Partial<Ticket>) => {
    setTickets((prev) =>
      prev.map((t) =>
        t.id === id
          ? { ...t, ...updates, updatedAt: new Date().toISOString() }
          : t,
      ),
    );
  }, []);

  const moveTicket = useCallback((id: string, columnId: ColumnId) => {
    setTickets((prev) =>
      prev.map((t) =>
        t.id === id
          ? { ...t, columnId, updatedAt: new Date().toISOString() }
          : t,
      ),
    );
  }, []);

  const deleteTicket = useCallback((id: string) => {
    setTickets((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const updateQuestion = useCallback(
    (ticketId: string, questionId: string, answer: string) => {
      setTickets((prev) =>
        prev.map((t) => {
          if (t.id !== ticketId) return t;
          return {
            ...t,
            questions: t.questions.map((q: Question) =>
              q.id === questionId ? { ...q, answer } : q,
            ),
            updatedAt: new Date().toISOString(),
          };
        }),
      );
    },
    [],
  );

  const ticketsByColumn = useCallback(
    (columnId: ColumnId) => tickets.filter((t) => t.columnId === columnId),
    [tickets],
  );

  return {
    tickets,
    loaded,
    addTicket,
    updateTicket,
    moveTicket,
    deleteTicket,
    updateQuestion,
    ticketsByColumn,
  };
}
