import logging

import numpy as np
from ctapipe.containers import EventType
from ctapipe.core.traits import Integer, List
from ctapipe_io_nectarcam import constants
from ctapipe_io_nectarcam.containers import NectarCAMDataContainer

from nectarchain.data.container import FlatFieldContainer
from nectarchain.makers.component import NectarCAMComponent

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
log.handlers = logging.getLogger("__main__").handlers

__all__ = ["PreFlatFieldComponent"]


class PreFlatFieldComponent(NectarCAMComponent):
    """
    Component that computes flat field coefficients from raw data.

    Parameters
    ----------
    window_shift: int
        time in ns before the peak to integrate charge (default value = 5)

    window_width: int
        duration of the extraction window in ns (default value = 12)

    gain: list
        array of gain value

    bad_pix: list
        list of bad pixels (default value = [])

    """

    window_shift = Integer(
        default_value=5,
        help="the time in ns before the peak to integrate charge",
    ).tag(config=True)

    window_width = Integer(
        default_value=12,
        help="the duration of the extraction window in ns",
    ).tag(config=True)

    gain = List(
        default_value=None,
        help="default gain value",
    ).tag(config=True)

    # hi_lo_ratio = Float(
    #    default_value=13.0,
    #    help="default high gain to low gain ratio",
    # ).tag(config=True)

    bad_pix = List(
        default_value=None,
        help="list of bad pixels",
    ).tag(config=True)

    def __init__(self, subarray, config=None, parent=None, *args, **kwargs):
        super().__init__(
            subarray=subarray, config=config, parent=parent, *args, **kwargs
        )

        self.__ucts_timestamp = []
        self.__event_type = []
        self.__event_id = []
        self.__amp_int_per_pix_per_event = []
        self.__FF_coef = []
        self.__bad_pixels = []

        print("gain")
        print(type(self.gain))
        print(self.gain)

        print("bad_pixels")
        print(type(self.bad_pix))
        print(self.bad_pix)

    def __call__(self, event: NectarCAMDataContainer, *args, **kwargs):
        if event.trigger.event_type.value == EventType.FLATFIELD.value:
            # print("event :", (self.__event_id, self.__event_type))
            self.__event_id.append(np.uint32(event.index.event_id))
            self.__event_type.append(event.trigger.event_type.value)
            self.__ucts_timestamp.append(event.nectarcam.tel[0].evt.ucts_timestamp)

            wfs = event.r0.tel[0].waveform

            # subtract pedestal using the mean of the 20 first samples
            wfs_pedsub = self.subtract_pedestal(wfs, 20)

            # get the masked array for integration window
            t_peak = np.argmax(wfs_pedsub, axis=-1)
            masked_wfs = self.make_masked_array(
                t_peak, self.window_shift, self.window_width
            )

            # mask bad pixels
            self.__bad_pixels.append(self.bad_pix)
            masked_wfs[:, self.bad_pix, :] = False

            # get integrated amplitude and mean amplitude over all pixels per event
            amp_int_per_pix_per_event = np.sum(
                wfs_pedsub, axis=-1, where=masked_wfs.astype("bool")
            )
            self.__amp_int_per_pix_per_event.append(amp_int_per_pix_per_event)
            # --< We could use ctapipe.image.extractor.LocalPeakWindowSum >--

            amp_int_per_pix_per_event_pe = amp_int_per_pix_per_event[:] / self.gain[:]
            mean_amp_cam_per_event_pe = np.mean(amp_int_per_pix_per_event_pe, axis=-1)

            eff = np.divide(
                amp_int_per_pix_per_event_pe,
                np.expand_dims(mean_amp_cam_per_event_pe, axis=-1),
            )

            FF_coef = np.ma.array(1.0 / eff, mask=eff == 0)
            self.__FF_coef.append(FF_coef)

    @staticmethod
    def subtract_pedestal(wfs, window=20):
        """
        Subtract the pedestal defined as the average of the first samples of each trace

        Args:
            wfs: raw wavefroms
            window: number of samples n to calculate the pedestal (default value is 20)

        Returns:
            wfs_pedsub: wavefroms subtracted from the pedestal
        """

        ped_mean = np.mean(wfs[:, :, 0:window], axis=2)
        wfs_pedsub = wfs - np.expand_dims(ped_mean, axis=-1)

        return wfs_pedsub

    @staticmethod
    def make_masked_array(t_peak, window_shift, window_width):
        """
        Define an array that will be used as a mask on the waveforms for the calculation
        of the integrated amplitude of the signal

        Args:
            t_peak: sample corresponding the the highest peak of the trace
            window_shift: number of samples before the peak to integrate charge
            window_width: duration of the extraction window in samples

        Returns:
            masked_wfs: a mask array
        """

        masked_wfs = np.zeros(
            shape=(constants.N_GAINS, constants.N_PIXELS, constants.N_SAMPLES),
            dtype=bool,
        )

        sample_times = np.expand_dims(np.arange(constants.N_SAMPLES), axis=(0, 1))
        t_peak = np.expand_dims(t_peak, axis=-1)

        t_signal_start = t_peak - window_shift
        t_signal_stop = t_peak + window_width - window_shift

        masked_wfs = (sample_times >= t_signal_start) & (sample_times < t_signal_stop)

        return masked_wfs

    def finish(self):
        output = FlatFieldContainer(
            run_number=FlatFieldContainer.fields["run_number"].type(self._run_number),
            npixels=FlatFieldContainer.fields["npixels"].type(self._npixels),
            pixels_id=FlatFieldContainer.fields["pixels_id"].dtype.type(
                self._pixels_id
            ),
            ucts_timestamp=FlatFieldContainer.fields["ucts_timestamp"].dtype.type(
                self.__ucts_timestamp
            ),
            event_type=FlatFieldContainer.fields["event_type"].dtype.type(
                self.__event_type
            ),
            event_id=FlatFieldContainer.fields["event_id"].dtype.type(self.__event_id),
            amp_int_per_pix_per_event=FlatFieldContainer.fields[
                "amp_int_per_pix_per_event"
            ].dtype.type(self.__amp_int_per_pix_per_event),
            FF_coef=FlatFieldContainer.fields["FF_coef"].dtype.type(self.__FF_coef),
            bad_pixels=FlatFieldContainer.fields["bad_pixels"].dtype.type(
                self.__bad_pixels
            ),
        )
        return output
