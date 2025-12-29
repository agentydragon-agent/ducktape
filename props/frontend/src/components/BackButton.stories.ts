import type { Meta, StoryObj } from '@storybook/svelte';
import BackButton from './BackButton.svelte';

const meta = {
  title: 'Components/BackButton',
  component: BackButton,
  tags: ['autodocs'],
} satisfies Meta<BackButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {},
};

export const CustomLabel: Story = {
  args: {
    label: '← Go Back',
  },
};

export const CustomHref: Story = {
  args: {
    href: '/custom-path',
    label: '← Return',
  },
};

export const CustomClass: Story = {
  args: {
    class: 'text-lg text-blue-600 hover:text-blue-800 font-semibold',
    label: '← Styled Back',
  },
};
