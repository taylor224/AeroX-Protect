import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { Bookmark, BookmarkInput } from '@/types/p6';

interface BookmarkList {
  count: number;
  items: Bookmark[];
}

export async function listBookmarks(cameraUuid: string, start?: number, end?: number): Promise<Bookmark[]> {
  const params: Record<string, unknown> = { camera_uuid: cameraUuid };
  if (start) params.start = start;
  if (end) params.end = end;
  const { data } = await api.get<ApiResponse<BookmarkList>>('/bookmarks', { params });
  return data.data?.items ?? [];
}

export async function createBookmark(body: BookmarkInput): Promise<Bookmark> {
  const { data } = await api.post<ApiResponse<Bookmark>>('/bookmarks', body);
  return data.data as Bookmark;
}

export async function updateBookmark(id: string, body: Partial<BookmarkInput>): Promise<Bookmark> {
  const { data } = await api.put<ApiResponse<Bookmark>>(`/bookmarks/${id}`, body);
  return data.data as Bookmark;
}

export async function deleteBookmark(id: string): Promise<void> {
  await api.delete(`/bookmarks/${id}`);
}
