'use client';

import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { TicketCard } from './ticket-card';
import type { Ticket } from '@/types';
import { Plus } from 'lucide-react';

interface KanbanColumnProps {
  id: string;
  title: string;
  tickets: Ticket[];
  onCardClick: (ticket: Ticket) => void;
  onAddClick?: () => void;
}

const COLUMN_ACCENT: Record<string, string> = {
  'backlog': 'border-t-slate-400',
  'to-refine': 'border-t-yellow-400',
  'to-research': 'border-t-blue-400',
  'researching': 'border-t-purple-400',
  'completed': 'border-t-green-400',
};

export function KanbanColumn({ id, title, tickets, onCardClick, onAddClick }: KanbanColumnProps) {
  return (
    <div className={`flex flex-col w-72 shrink-0 bg-muted/40 rounded-xl border-t-2 ${COLUMN_ACCENT[id] ?? 'border-t-border'}`}>
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">{title}</span>
          <span className="text-xs text-muted-foreground bg-muted rounded-full px-1.5 py-0.5 leading-none">
            {tickets.length}
          </span>
        </div>
        {onAddClick && (
          <Button variant="ghost" size="icon" className="size-6" onClick={onAddClick}>
            <Plus className="size-3.5" />
          </Button>
        )}
      </div>

      <ScrollArea className="flex-1 px-2 pb-2">
        <div className="space-y-2">
          {tickets.map(ticket => (
            <TicketCard
              key={ticket.id}
              ticket={ticket}
              onClick={() => onCardClick(ticket)}
            />
          ))}
          {tickets.length === 0 && (
            <div className="text-xs text-muted-foreground/60 text-center py-6">
              Empty
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
