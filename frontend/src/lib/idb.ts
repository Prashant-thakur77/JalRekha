import { openDB } from 'idb';
import type { DBSchema } from 'idb';

export interface PendingAttachment {
  blob: Blob;
  name: string;
  type: string;
}

export interface PendingReport {
  id?: number;
  site_id: string;
  reporter_name: string;
  reporter_role: string;
  transcript_text: string;
  photo_attachment?: PendingAttachment;
  audio_attachment?: PendingAttachment;
  offline_created: boolean;
  createdAt: number;
}

interface JalRekhaDB extends DBSchema {
  reports: {
    value: PendingReport;
    key: number;
    indexes: { 'by-date': number };
  };
}

const dbPromise = openDB<JalRekhaDB>('jalrekha-db', 1, {
  upgrade(db) {
    const store = db.createObjectStore('reports', {
      keyPath: 'id',
      autoIncrement: true,
    });
    store.createIndex('by-date', 'createdAt');
  },
});

export async function saveReportOffline(report: Omit<PendingReport, 'id' | 'createdAt'>) {
  const db = await dbPromise;
  await db.add('reports', {
    ...report,
    createdAt: Date.now(),
  });
}

export function toPendingAttachment(file: File | null | undefined): PendingAttachment | undefined {
  if (!file) {
    return undefined;
  }

  return {
    blob: file,
    name: file.name,
    type: file.type || 'application/octet-stream',
  };
}

export function attachmentToFile(
  attachment: PendingAttachment,
  fallbackName: string,
): File {
  const name = attachment.name || fallbackName;
  const type = attachment.type || attachment.blob.type || 'application/octet-stream';
  return new File([attachment.blob], name, { type });
}

export async function getPendingReports() {
  const db = await dbPromise;
  return db.getAllFromIndex('reports', 'by-date');
}

export async function deleteReportOffline(id: number) {
  const db = await dbPromise;
  await db.delete('reports', id);
}

export async function clearOfflineReports() {
  const db = await dbPromise;
  await db.clear('reports');
}
