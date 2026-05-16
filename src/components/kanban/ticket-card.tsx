'use client';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { Ticket } from '@/types';
import { MessageSquare, CheckCircle2 } from 'lucide-react';

interface TicketCardProps {
  ticket: Ticket;
  onClick: () => void;
}

export function TicketCard({ ticket, onClick }: TicketCardProps) {
  const answeredCount = ticket.questions.filter(q => q.answer.trim()).length;
  const totalQuestions = ticket.questions.length;

  return (
    <Card
      className="p-3 cursor-pointer hover:shadow-md transition-shadow group"
      onClick={onClick}
    >
      <p className="text-sm font-medium leading-snug group-hover:text-primary transition-colors">
        {ticket.title}
      </p>

      {ticket.description && (
        <p className="text-xs text-muted-foreground mt-1 line-clamp-2 leading-relaxed">
          {ticket.description}
        </p>
      )}

      {(totalQuestions > 0 || ticket.researchOutput) && (
        <div className="flex items-center gap-2 mt-2.5">
          {totalQuestions > 0 && (
            <Badge variant="secondary" className="text-xs gap-1 font-normal px-1.5 py-0.5">
              <MessageSquare className="size-3" />
              {answeredCount}/{totalQuestions}
            </Badge>
          )}
          {ticket.researchOutput && (
            <Badge variant="secondary" className="text-xs gap-1 font-normal px-1.5 py-0.5 text-green-700 dark:text-green-400">
              <CheckCircle2 className="size-3" />
              Done
            </Badge>
          )}
        </div>
      )}
    </Card>
  );
}
