import type { Meta, StoryObj } from '@storybook/svelte';
import ExamplesPage from '../../routes/examples/+page.svelte';
import { mockExampleDetail } from '../mockData';

const meta = {
  title: 'Pages/Example Detail',
  component: ExamplesPage,
  tags: ['autodocs'],
  parameters: {
    layout: 'fullscreen',
  },
} satisfies Meta<ExamplesPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    data: {
      example: mockExampleDetail,
    },
  },
};

export const ErrorState: Story = {
  args: {
    data: {
      example: null,
      error: 'Example not found',
    },
  },
};
