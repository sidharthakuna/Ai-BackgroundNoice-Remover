package com.sidhartha.controller;

import com.sidhartha.service.NoiseRemovalService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("api/v1/audio")
public class AudioController {

    @Autowired
    NoiseRemovalService noiceRemovalService; //spring give this from the service class
    @PostMapping("/enhance")
    public ResponseEntity<byte[]> receiveFile(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "demucs" , defaultValue = "false") boolean useDemucs
            ) throws Exception {
        //===========
        //for api call
//        String uuid = noiceRemovalService.createProduction(file);
//        noiceRemovalService.startProduction(uuid);
//        String downloadUrl = noiceRemovalService.pollUntilDone(uuid);
//        byte[] cleanedAudio = noiceRemovalService.downloadFile(downloadUrl);
        //==============

        //for the "python" script "Ai"
        byte[] cleanedAudio = noiceRemovalService.removeNoise(file, useDemucs);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.valueOf("audio/wav"));  // always wav output
        headers.setContentDispositionFormData("attachment", "enhanced_audio.wav"); // always wav

        return ResponseEntity.ok()
                .headers(headers)
                .body(cleanedAudio);
    }

    @GetMapping("/test")
    public String testApi(){
        return noiceRemovalService.testApi(); //call the service method
    }

}
