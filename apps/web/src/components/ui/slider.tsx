import * as RadixSlider from '@radix-ui/react-slider';

export function Slider({
  value,
  max,
  step,
  label,
  onValueChange,
  onValueCommit,
}: {
  value: number[];
  max: number;
  step: number;
  label: string;
  onValueChange: (value: number[]) => void;
  onValueCommit?: (value: number[]) => void;
}) {
  return (
    <RadixSlider.Root
      className="relative flex h-5 w-full touch-none select-none items-center"
      value={value}
      max={max}
      step={step}
      minStepsBetweenThumbs={0}
      onValueChange={onValueChange}
      onValueCommit={onValueCommit}
    >
      <RadixSlider.Track className="relative h-1 grow rounded-full bg-line">
        <RadixSlider.Range className="absolute h-full rounded-full bg-accent" />
      </RadixSlider.Track>
      {value.map((_, index) => (
        <RadixSlider.Thumb
          key={index}
          aria-label={value.length > 1 ? `${label} ${index === 0 ? 'minimum' : 'maximum'}` : label}
          className="block h-3.5 w-3.5 rounded-full border-2 border-accent bg-surface"
        />
      ))}
    </RadixSlider.Root>
  );
}
