import type { Meta, StoryObj } from '@storybook/svelte';
import SnapshotsPage from '../../routes/snapshots/+page.svelte';
import { mockSnapshotsList } from '../mockData';

const meta = {
  title: 'Pages/Snapshots List',
  component: SnapshotsPage,
  tags: ['autodocs'],
  parameters: {
    layout: 'fullscreen',
  },
} satisfies Meta<SnapshotsPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    data: {
      snapshots: mockSnapshotsList,
    },
  },
};

export const EmptyState: Story = {
  args: {
    data: {
      snapshots: [],
    },
  },
};

export const SingleSnapshot: Story = {
  args: {
    data: {
      snapshots: [mockSnapshotsList[0]],
    },
  },
};
