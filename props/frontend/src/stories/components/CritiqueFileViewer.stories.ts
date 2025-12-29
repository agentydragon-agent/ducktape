import type { Meta, StoryObj } from '@storybook/svelte';
import CritiqueFileViewer from '../../components/CritiqueFileViewer.svelte';
import {
  mockFileContent,
  mockFileTps,
  mockFileFps,
  mockCritiqueIssues,
  mockGradingEdges,
  mockSnapshotSlug,
} from '../mockData';

const meta = {
  title: 'Components/CritiqueFileViewer',
  component: CritiqueFileViewer,
  tags: ['autodocs'],
  parameters: {
    layout: 'padded',
  },
  argTypes: {
    snapshotSlug: { control: 'text' },
  },
} satisfies Meta<CritiqueFileViewer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    file: mockFileContent,
    tps: [],
    fps: [],
    critiqueIssues: [],
    gradingEdges: [],
  },
};

export const WithGroundTruthOnly: Story = {
  args: {
    file: mockFileContent,
    tps: mockFileTps,
    fps: mockFileFps,
    critiqueIssues: [],
    gradingEdges: [],
    snapshotSlug: mockSnapshotSlug,
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
