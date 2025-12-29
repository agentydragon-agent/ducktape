import type { Meta, StoryObj } from '@storybook/svelte';
import OverviewPage from '../../routes/+page.svelte';
import { mockOverview } from '../mockData';

const meta = {
  title: 'Pages/Overview',
  component: OverviewPage,
  tags: ['autodocs'],
  parameters: {
    layout: 'fullscreen',
  },
} satisfies Meta<OverviewPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    data: {
      overview: mockOverview,
    },
  },
};

export const EmptyState: Story = {
  args: {
    data: {
      overview: {
        definitions: [],
        example_counts: {},
        total_definitions: 0,
      },
    },
  },
};
