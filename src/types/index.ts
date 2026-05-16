export type ColumnId = 'backlog' | 'to-refine' | 'to-research' | 'researching' | 'completed';

export interface Question {
  id: string;
  text: string;
  answer: string;
}

export interface Ticket {
  id: string;
  title: string;
  description: string;
  columnId: ColumnId;
  questions: Question[];
  researchOutput?: string;
  createdAt: string;
  updatedAt: string;
}

export const COLUMNS: { id: ColumnId; title: string }[] = [
  { id: 'backlog', title: 'Backlog' },
  { id: 'to-refine', title: 'To Refine' },
  { id: 'to-research', title: 'To Research' },
  { id: 'researching', title: 'Researching' },
  { id: 'completed', title: 'Completed' },
];
