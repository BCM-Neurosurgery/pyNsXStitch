from brpylib import NsxFile, NevFile

AUDIO_CHAN_NAMES = [
    'mic',
    'audio'
]


def remove_audio_nsx(nsx_file: NsxFile, output_filename: str):

    non_audio_channels = []
    for i, metadata in enumerate(nsx_file.extended_headers):
        for forbidden in AUDIO_CHAN_NAMES:
            if forbidden in metadata['ElectrodeLabel']:
                print(f'Removing channel {metadata["ElectrodeLabel"]}')
        else:
            non_audio_channels.append(i)

    return nsx_file.savesubsetnsx(non_audio_channels, out_file=output_filename)