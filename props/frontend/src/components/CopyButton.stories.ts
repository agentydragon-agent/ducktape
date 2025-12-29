import type { Meta, StoryObj } from '@storybook/svelte';
import CopyButton from './CopyButton.svelte';

const meta = {
  title: 'Components/CopyButton',
  component: CopyButton,
  tags: ['autodocs'],
} satisfies Meta<CopyButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    text: 'https://example.com/some/url/to/copy',
  },
};

export const CustomLabel: Story = {
  args: {
    text: "console.log('Hello, World!');",
    label: 'Copy Code',
  },
};

export const CustomSuccessMessage: Story = {
  args: {
    text: 'git clone https://github.com/example/repo.git',
    label: 'Copy',
    successMessage: 'Git command copied!',
  },
};

export const LongText: Story = {
  args: {
    text: 'https://example.com/very/long/url/that/might/need/to/be/copied/for/deep/linking/purposes',
    label: 'Copy URL',
  },
};
