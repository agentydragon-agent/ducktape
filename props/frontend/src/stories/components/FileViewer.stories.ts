import type { Meta, StoryObj } from '@storybook/svelte';
import FileViewer from '../../components/FileViewer.svelte';
import { mockFileContent, mockFileTps, mockFileFps, mockSnapshotSlug } from '../mockData';

const meta = {
  title: 'Components/FileViewer',
  component: FileViewer,
  tags: ['autodocs'],
  parameters: {
    layout: 'padded',
  },
  argTypes: {
    snapshotSlug: { control: 'text' },
    targetOccurrenceId: { control: 'text' },
  },
} satisfies Meta<FileViewer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    file: mockFileContent,
    tps: [],
    fps: [],
  },
};

export const WithTruePositive: Story = {
  args: {
    file: mockFileContent,
    tps: mockFileTps,
    fps: [],
    snapshotSlug: mockSnapshotSlug,
  },
};

export const WithFalsePositive: Story = {
  args: {
    file: mockFileContent,
    tps: [],
    fps: mockFileFps,
    snapshotSlug: mockSnapshotSlug,
  },
};

export const WithBothTpAndFp: Story = {
  args: {
    file: mockFileContent,
    tps: mockFileTps,
    fps: mockFileFps,
    snapshotSlug: mockSnapshotSlug,
  },
};

export const WithTargetedOccurrence: Story = {
  args: {
    file: mockFileContent,
    tps: mockFileTps,
    fps: [],
    snapshotSlug: mockSnapshotSlug,
    targetOccurrenceId: 'occ-tp-001',
  },
};
