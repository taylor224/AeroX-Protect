import { Toaster as Sonner } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = (props: ToasterProps) => (
  <Sonner
    position="top-center"
    richColors
    toastOptions={{
      style: { borderRadius: '4px', fontFamily: 'Pretendard, -apple-system, sans-serif' },
    }}
    {...props}
  />
);

export { Toaster };
