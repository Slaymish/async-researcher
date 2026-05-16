'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';

interface AddTicketDialogProps {
  open: boolean;
  onClose: () => void;
  onAdd: (title: string, description: string) => void;
}

export function AddTicketDialog({ open, onClose, onAdd }: AddTicketDialogProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    onAdd(title.trim(), description.trim());
    setTitle('');
    setDescription('');
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add research idea</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Title</label>
            <Input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="What do you want to research?"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Description <span className="text-muted-foreground font-normal">(optional)</span></label>
            <Textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Any additional context..."
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!title.trim()}>Add to backlog</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
