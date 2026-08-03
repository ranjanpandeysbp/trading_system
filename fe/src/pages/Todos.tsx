import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Pencil, Plus, Search, Trash2, Undo2, X } from 'lucide-react'
import { apiErrorMessage, createTodo, deleteTodo, fetchTodos, updateTodo, type Todo, type TodoStatus } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const STATUS_FILTERS: Array<{ value: TodoStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'done', label: 'Done' },
]

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

function NewTodoForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')

  const mutation = useMutation({
    mutationFn: () => createTodo({ title, notes: notes.trim() || undefined }),
    onSuccess: () => {
      setTitle('')
      setNotes('')
      setOpen(false)
      onCreated()
    },
  })

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)} className="whitespace-nowrap">
        <Plus size={16} /> New todo
      </Button>
    )
  }

  return (
    <Card className="w-full">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold text-white">New todo</h3>
        <button type="button" onClick={() => setOpen(false)} className="text-slate-400 hover:text-white">
          <X size={18} />
        </button>
      </div>
      <FormField label="Title">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What needs doing?" autoFocus />
      </FormField>
      <FormField label="Notes (optional)">
        <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Any details..." />
      </FormField>
      {mutation.isError && <Alert type="error">{apiErrorMessage(mutation.error)}</Alert>}
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <Button onClick={() => mutation.mutate()} disabled={!title.trim() || mutation.isPending}>
          {mutation.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Add todo'}
        </Button>
      </div>
    </Card>
  )
}

function TodoCard({ todo }: { todo: Todo }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(todo.title)
  const [notes, setNotes] = useState(todo.notes ?? '')

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['todos'] })

  const statusMutation = useMutation({
    mutationFn: (status: TodoStatus) => updateTodo(todo.id, { status }),
    onSuccess: invalidate,
  })

  const editMutation = useMutation({
    mutationFn: () => updateTodo(todo.id, { title, notes: notes.trim() }),
    onSuccess: () => {
      setEditing(false)
      invalidate()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteTodo(todo.id),
    onSuccess: invalidate,
  })

  const done = todo.status === 'done'

  return (
    <Card className={done ? 'opacity-60' : ''}>
      {editing ? (
        <div className="space-y-3">
          <FormField label="Title">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
          </FormField>
          <FormField label="Notes">
            <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </FormField>
          {editMutation.isError && <Alert type="error">{apiErrorMessage(editMutation.error)}</Alert>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
            <Button size="sm" onClick={() => editMutation.mutate()} disabled={!title.trim() || editMutation.isPending}>
              {editMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Save'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <button
            type="button"
            onClick={() => statusMutation.mutate(done ? 'pending' : 'done')}
            disabled={statusMutation.isPending}
            className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
              done ? 'border-emerald-500/50 bg-emerald-500/20 text-emerald-400' : 'border-slate-600 text-transparent hover:border-slate-500'
            }`}
            title={done ? 'Mark as pending' : 'Mark as done'}
          >
            <Check size={13} />
          </button>

          <div className="min-w-0 flex-1">
            <p className={`break-words font-medium text-white ${done ? 'line-through decoration-slate-500' : ''}`}>{todo.title}</p>
            {todo.notes && <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-400">{todo.notes}</p>}
            <p className="mt-2 text-[11px] text-slate-500">
              {done ? 'Completed' : 'Created'} {new Date(`${todo.updated_at}Z`).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {done && (
              <button
                type="button"
                onClick={() => statusMutation.mutate('pending')}
                className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-300"
                title="Undo"
              >
                <Undo2 size={15} />
              </button>
            )}
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-300"
              title="Edit"
            >
              <Pencil size={15} />
            </button>
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Delete "${todo.title}"?`)) deleteMutation.mutate()
              }}
              disabled={deleteMutation.isPending}
              className="rounded-lg p-1.5 text-slate-500 hover:bg-rose-500/10 hover:text-rose-400"
              title="Delete"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>
      )}
    </Card>
  )
}

export default function TodosPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<TodoStatus | 'all'>('all')
  const debouncedSearch = useDebounced(search, 300)

  const query = useQuery({
    queryKey: ['todos', debouncedSearch, status],
    queryFn: () => fetchTodos({ search: debouncedSearch || undefined, status: status === 'all' ? undefined : status }),
  })

  const todos = query.data?.todos ?? []
  const pendingCount = todos.filter((t) => t.status === 'pending').length

  return (
    <div>
      <PageHeader title="Todos" description="Personal task list — separate from your trading setups. Create, search, update status, and delete." />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1 sm:max-w-xs">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search todos..."
              className="pl-9"
            />
          </div>
          <Select value={status} onChange={(e) => setStatus(e.target.value as TodoStatus | 'all')} className="sm:w-40">
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </Select>
        </div>
        <NewTodoForm onCreated={() => query.refetch()} />
      </div>

      {query.isLoading && <Loading message="Loading todos..." />}
      {query.isError && <Alert type="error">{apiErrorMessage(query.error)}</Alert>}

      {!query.isLoading && !query.isError && (
        todos.length === 0 ? (
          <Card>
            <p className="py-8 text-center text-sm text-slate-400">
              {search || status !== 'all' ? 'No todos match your search/filter.' : 'No todos yet — add one above to get started.'}
            </p>
          </Card>
        ) : (
          <>
            <p className="mb-2 text-xs text-slate-500">{pendingCount} pending · {todos.length} total</p>
            <div className="space-y-2.5">
              {todos.map((t) => <TodoCard key={t.id} todo={t} />)}
            </div>
          </>
        )
      )}
    </div>
  )
}
