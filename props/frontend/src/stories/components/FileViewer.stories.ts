import type { Meta, StoryObj } from '@storybook/svelte';
import FileViewer from '../../components/FileViewer.svelte';
import {
  mockFileContent,
  mockFileTps,
  mockFileFps,
  mockCritiqueIssues,
  mockGradingEdges,
  mockSnapshotSlug,
} from '../mockData';

const meta = {
  title: 'Components/FileViewer',
  component: FileViewer,
  tags: ['autodocs'],
  parameters: {
    layout: 'padded',
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

export const WithCritiquesOnly: Story = {
  args: {
    file: mockFileContent,
    tps: [],
    fps: [],
    critiqueIssues: mockCritiqueIssues,
    gradingEdges: [],
    snapshotSlug: mockSnapshotSlug,
  },
};

export const WithCritiquesAndGroundTruth: Story = {
  args: {
    file: mockFileContent,
    tps: mockFileTps,
    fps: mockFileFps,
    critiqueIssues: mockCritiqueIssues,
    gradingEdges: [],
    snapshotSlug: mockSnapshotSlug,
  },
};

export const WithGradingEdges: Story = {
  args: {
    file: mockFileContent,
    tps: mockFileTps,
    fps: mockFileFps,
    critiqueIssues: mockCritiqueIssues,
    gradingEdges: mockGradingEdges,
    snapshotSlug: mockSnapshotSlug,
  },
};
