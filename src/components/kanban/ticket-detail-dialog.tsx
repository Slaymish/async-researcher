'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { Ticket, ColumnId } from '@/types';
import { COLUMNS } from '@/types';
import { Trash2 } from 'lucide-react';

interface TicketDetailDialogProps {
  ticket: Ticket | null;
  onClose: () => void;
  onMove: (id: string, columnId: ColumnId) => void;
  onUpdateQuestion: (ticketId: string, questionId: string, answer: string) => void;
  onDelete: (id: string) => void;
}

const COLUMN_COLORS: Record<ColumnId, string> = {
  'backlog': 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  'to-refine': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  'to-research': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  'researching': 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  'completed': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
};

export function TicketDetailDialog({
  ticket,
  onClose,
  onMove,
  onUpdateQuestion,
  onDelete,
}: TicketDetailDialogProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  if (!ticket) return null;

  const columnLabel = COLUMNS.find(c => c.id === ticket.columnId)?.title ?? ticket.columnId;

  function handleAnswerChange(questionId: string, value: string) {
    setAnswers(prev => ({ ...prev, [questionId]: value }));
  }

  function handleAnswerBlur(questionId: string) {
    const value = answers[questionId];
    if (value !== undefined) {
      onUpdateQuestion(ticket!.id, questionId, value);
    }
  }

  function getAnswer(questionId: string, stored: string) {
    return answers[questionId] ?? stored;
  }

  const canMoveToRefine = ticket.columnId === 'backlog';

  const canMoveToResearch =
    ticket.columnId === 'to-refine' &&
    ticket.questions.length > 0 &&
    ticket.questions.every(q => q.answer.trim() || (answers[q.id] ?? '').trim());

  return (
    <Dialog open={!!ticket} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-start justify-between gap-2 pr-6">
            <DialogTitle className="text-left leading-snug">{ticket.title}</DialogTitle>
            <Badge className={`shrink-0 text-xs font-medium border-0 ${COLUMN_COLORS[ticket.columnId]}`}>
              {columnLabel}
            </Badge>
          </div>
        </DialogHeader>

        <ScrollArea className="flex-1 -mx-6 px-6">
          <div className="space-y-5 pb-2">
            {ticket.description && (
              <p className="text-sm text-muted-foreground leading-relaxed">{ticket.description}</p>
            )}

            {ticket.questions.length > 0 && (
              <>
                <Separator />
                <div className="space-y-4">
                  <p className="text-sm font-medium">Questions to answer</p>
                  {ticket.questions.map(q => (
                    <div key={q.id} className="space-y-1.5">
                      <p className="text-sm">{q.text}</p>
                      <Textarea
                        value={getAnswer(q.id, q.answer)}
                        onChange={e => handleAnswerChange(q.id, e.target.value)}
                        onBlur={() => handleAnswerBlur(q.id)}
                        placeholder="Your answer..."
                        rows={2}
                        className="text-sm"
                        disabled={ticket.columnId === 'researching' || ticket.columnId === 'completed'}
                      />
                    </div>
                  ))}
                </div>
              </>
            )}

            {ticket.researchOutput && (
              <>
                <Separator />
                <div className="space-y-2">
                  <p className="text-sm font-medium">Research output</p>
                  <div className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed bg-muted/50 rounded-md p-3">
                    {ticket.researchOutput}
                  </div>
                </div>
              </>
            )}
          </div>
        </ScrollArea>

        <div className="flex items-center justify-between pt-2 border-t">
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => { onDelete(ticket.id); onClose(); }}
          >
            <Trash2 className="size-4 mr-1.5" />
            Delete
          </Button>

          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
            {canMoveToRefine && (
              <Button size="sm" onClick={() => { onMove(ticket.id, 'to-refine'); onClose(); }}>
                Move to refine →
              </Button>
            )}
            {canMoveToResearch && (
              <Button size="sm" onClick={() => { onMove(ticket.id, 'to-research'); onClose(); }}>
                Ready to research →
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
