import * as RadixSwitch from '@radix-ui/react-switch';

export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <RadixSwitch.Root
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onCheckedChange={onCheckedChange}
      className="relative h-4 w-7 shrink-0 rounded-full bg-line transition-colors data-[state=checked]:bg-accent disabled:opacity-50"
    >
      <RadixSwitch.Thumb className="block h-3 w-3 translate-x-0.5 rounded-full bg-surface shadow transition-transform data-[state=checked]:translate-x-[14px]" />
    </RadixSwitch.Root>
  );
}
