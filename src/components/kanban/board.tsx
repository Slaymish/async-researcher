'use client';

import { useState } from 'react';
import { useKanban } from '@/hooks/use-kanban';
import { KanbanColumn } from './column';
import { AddTicketDialog } from './add-ticket-dialog';
import { TicketDetailDialog } from './ticket-detail-dialog';
import { COLUMNS } from '@/types';
import type { Ticket } from '@/types';

export function KanbanBoard() {
  const { loaded, addTicket, moveTicket, deleteTicket, updateQuestion, ticketsByColumn } = useKanban();
  const [addOpen, setAddOpen] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);

  if (!loaded) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Loading...
      </div>
    );
  }

  return (
    <>
      <div className="flex-1 overflow-x-auto">
        <div className="flex gap-3 p-4 h-full min-h-0">
          {COLUMNS.map(col => (
            <KanbanColumn
              key={col.id}
              id={col.id}
              title={col.title}
              tickets={ticketsByColumn(col.id)}
              onCardClick={setSelectedTicket}
              onAddClick={col.id === 'backlog' ? () => setAddOpen(true) : undefined}
            />
          ))}
        </div>
      </div>

      <AddTicketDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onAdd={addTicket}
      />

      <TicketDetailDialog
        ticket={selectedTicket}
        onClose={() => setSelectedTicket(null)}
        onMove={(id, col) => {
          moveTicket(id, col);
          setSelectedTicket(null);
        }}
        onUpdateQuestion={updateQuestion}
        onDelete={deleteTicket}
      />
    </>
  );
}
