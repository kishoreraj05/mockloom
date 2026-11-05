import { cva, type VariantProps } from 'class-variance-authority';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

const variants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-accent-ink hover:opacity-90',
        secondary: 'border border-line bg-surface text-ink hover:bg-raised',
        ghost: 'text-muted hover:bg-raised hover:text-ink',
        danger: 'border border-line bg-surface text-bad hover:bg-raised',
      },
      size: {
        sm: 'h-7 px-2 text-xs',
        md: 'h-8 px-3 text-[13px]',
        icon: 'h-7 w-7',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
);

type Props = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof variants>;

export const Button = forwardRef<HTMLButtonElement, Props>(({ className, variant, size, type, ...props }, ref) => (
  <button ref={ref} type={type ?? 'button'} className={cn(variants({ variant, size }), className)} {...props} />
));
Button.displayName = 'Button';
