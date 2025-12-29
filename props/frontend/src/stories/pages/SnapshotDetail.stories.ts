import type { Meta, StoryObj } from '@storybook/svelte';
import SnapshotDetailPage from '../../routes/snapshots/[...slug]/+page.svelte';
import { mockSnapshotDetail, mockSnapshotTree } from '../mockData';

const meta = {
  title: 'Pages/Snapshot Detail',
  component: SnapshotDetailPage,
  tags: ['autodocs'],
  parameters: {
    layout: 'fullscreen',
  },
} satisfies Meta<SnapshotDetailPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    data: {
      snapshot: mockSnapshotDetail,
      tree: mockSnapshotTree,
      slug: mockSnapshotDetail.slug,
      issueId: undefined,
      occurrenceId: undefined,
      fileToShow: undefined,
    },
  },
};

export const WithDeepLink: Story = {
  args: {
    data: {
      snapshot: mockSnapshotDetail,
      tree: mockSnapshotTree,
      slug: mockSnapshotDetail.slug,
      issueId: 'tp-001',
      occurrenceId: 'occ-tp-001',
      fileToShow: undefined,
    },
  },
};
