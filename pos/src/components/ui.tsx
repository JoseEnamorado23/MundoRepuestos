// Componentes base (estilo shadcn/ui sobre Radix). Objetivos táctiles ≥ 44 px, foco visible, alto contraste.
import * as DialogPrimitive from '@radix-ui/react-dialog'
import * as LabelPrimitive from '@radix-ui/react-label'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const boton = cva(
  'inline-flex items-center justify-center gap-2 rounded-lg font-semibold select-none transition-colors disabled:opacity-50 disabled:pointer-events-none',
  {
    variants: {
      variante: {
        primario: 'bg-marca text-marcatexto hover:brightness-110',
        secundario: 'bg-superficie2 text-texto border-2 border-borde hover:border-texto',
        fantasma: 'text-texto hover:bg-superficie2',
        ok: 'bg-ok text-white hover:brightness-110',
        peligro: 'bg-error text-white hover:brightness-110',
      },
      tamano: {
        normal: 'min-h-11 px-4 text-base',
        grande: 'min-h-14 px-6 text-xl',
        icono: 'min-h-11 min-w-11 p-0',
      },
    },
    defaultVariants: { variante: 'secundario', tamano: 'normal' },
  },
)

export interface BotonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof boton> {
  asChild?: boolean
}
export const Button = forwardRef<HTMLButtonElement, BotonProps>(function Button(
  { className, variante, tamano, asChild, type = 'button', ...p },
  ref,
) {
  const C = asChild ? Slot : 'button'
  return <C ref={ref} type={type} className={cn(boton({ variante, tamano }), className)} {...p} />
})

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...p },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        'min-h-11 w-full rounded-lg border-2 border-borde bg-superficie px-3 text-lg text-texto placeholder:text-suave/70',
        'focus:border-acento disabled:opacity-60',
        className,
      )}
      {...p}
    />
  )
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, ...p },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cn(
        'min-h-11 w-full rounded-lg border-2 border-borde bg-superficie px-3 text-lg text-texto focus:border-acento disabled:opacity-60',
        className,
      )}
      {...p}
    />
  )
})

export function Campo({ etiqueta, ayuda, children, className }: { etiqueta: string; ayuda?: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <LabelPrimitive.Root className="text-sm font-semibold text-suave">{etiqueta}</LabelPrimitive.Root>
      {children}
      {ayuda && <p className="text-sm text-suave">{ayuda}</p>}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border-2 border-borde bg-superficie2 px-1.5 py-0.5 font-mono text-xs font-bold text-texto">
      {children}
    </kbd>
  )
}

const tonos = {
  info: { c: 'border-acento text-texto', i: <Info className="size-5 shrink-0 text-acento" aria-hidden /> },
  ok: { c: 'border-ok text-texto', i: <CheckCircle2 className="size-5 shrink-0 text-ok" aria-hidden /> },
  aviso: { c: 'border-aviso text-texto', i: <AlertTriangle className="size-5 shrink-0 text-aviso" aria-hidden /> },
  error: { c: 'border-error text-texto', i: <AlertTriangle className="size-5 shrink-0 text-error" aria-hidden /> },
} as const

export function Aviso({ tipo = 'info', children, className }: { tipo?: keyof typeof tonos; children: ReactNode; className?: string }) {
  const t = tonos[tipo]
  return (
    <div role={tipo === 'error' ? 'alert' : 'status'} className={cn('flex items-start gap-2 rounded-lg border-2 bg-superficie p-3 text-base', t.c, className)}>
      {t.i}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

export function Cargando({ texto = 'Cargando…' }: { texto?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-suave" role="status">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      {texto}
    </span>
  )
}

export interface ModalProps {
  abierto: boolean
  onCerrar: () => void
  titulo: string
  descripcion?: string
  children: ReactNode
  ancho?: 'sm' | 'md' | 'lg' | 'xl'
  /** Impide cerrar con Esc o clic fuera (operaciones que no se pueden abandonar). */
  bloquear?: boolean
}
const anchos = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-5xl' }

export function Modal({ abierto, onCerrar, titulo, descripcion, children, ancho = 'md', bloquear }: ModalProps) {
  return (
    <DialogPrimitive.Root open={abierto} onOpenChange={(o) => !o && !bloquear && onCerrar()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content
          onEscapeKeyDown={(e) => bloquear && e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          aria-describedby={descripcion ? undefined : undefined}
          className={cn(
            'fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-xl border-2 border-borde bg-superficie p-5 shadow-2xl',
            anchos[ancho],
          )}
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <DialogPrimitive.Title className="text-2xl font-bold">{titulo}</DialogPrimitive.Title>
              {descripcion ? (
                <DialogPrimitive.Description className="mt-1 text-base text-suave">{descripcion}</DialogPrimitive.Description>
              ) : (
                <DialogPrimitive.Description className="sr-only">{titulo}</DialogPrimitive.Description>
              )}
            </div>
            {!bloquear && (
              <DialogPrimitive.Close asChild>
                <Button variante="fantasma" tamano="icono" aria-label="Cerrar">
                  <X className="size-6" />
                </Button>
              </DialogPrimitive.Close>
            )}
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
