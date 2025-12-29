import type { Meta, StoryObj } from '@storybook/svelte';
import Breadcrumb from './Breadcrumb.svelte';

const meta = {
  title: 'Components/Breadcrumb',
  component: Breadcrumb,
  tags: ['autodocs'],
} satisfies Meta<Breadcrumb>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SingleItem: Story = {
  args: {
    items: [{ label: 'snapshot-name' }],
  },
};

export const WithPath: Story = {
  args: {
    items: [
      { label: 'snapshot-name', href: '/snapshots/snapshot-name' },
      { label: 'src' },
      { label: 'components' },
      { label: 'Button.tsx' },
    ],
  },
};

export const DeepPath: Story = {
  args: {
    items: [
      { label: 'snapshot-name', href: '/snapshots/snapshot-name' },
      { label: 'src' },
      { label: 'features' },
      { label: 'auth' },
      { label: 'components' },
      { label: 'LoginForm.tsx' },
    ],
  },
};

export const AllLinked: Story = {
  args: {
    items: [
      { label: 'Home', href: '/' },
      { label: 'Snapshots', href: '/snapshots' },
      { label: 'snapshot-1', href: '/snapshots/snapshot-1' },
      { label: 'file.py' },
    ],
  },
};
