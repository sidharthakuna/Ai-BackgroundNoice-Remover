package com.sidhartha.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jdk.jfr.ContentType;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import javax.smartcardio.ATR;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

@Service
public class NoiceRemovalService {

    @Value("${auphonic.username}")
    private String username;

    @Value("${auphonic.password}")
    private String password;

    RestTemplate restTemplate = new RestTemplate(getClientHttpRequestFactory());

    private SimpleClientHttpRequestFactory getClientHttpRequestFactory() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10000);
        factory.setReadTimeout(120000);
        return factory;
    }

    

    public String testApi(){
        HttpHeaders headers = new HttpHeaders();
        headers.setBasicAuth(username,password);
        HttpEntity<String> entity=new HttpEntity<>(headers);
        ResponseEntity<String> response=restTemplate.exchange(
                "https://auphonic.com/api/simple/productions.json",
                HttpMethod.GET,
                entity,
                String.class
        );


        return response.getBody();
    }

    public String createProduction(MultipartFile file) throws Exception{

        HttpHeaders headers=new HttpHeaders();
        headers.setBasicAuth(username,password);
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);

        MultiValueMap<String,Object> body = new LinkedMultiValueMap<>();
        body.add("input_file",new ByteArrayResource(file.getBytes()){
            @Override
            public String getFilename(){
                return file.getOriginalFilename();
            }
        });
        body.add("denoise",true);

        HttpEntity<MultiValueMap<String,Object>> entity=new HttpEntity<>(body,headers);

        System.out.println("file size being sent : "+file.getSize());

        ResponseEntity<String> response=restTemplate.exchange(
                "https://auphonic.com/api/simple/productions.json",
                HttpMethod.POST,
                entity,
                String.class
        );
        ObjectMapper mapper = new ObjectMapper();
        JsonNode root= mapper.readTree(response.getBody());
        String uuid=root.path("data").path("uuid").asText();
        return uuid;
    }

    public void startProduction(String uuid){
        HttpHeaders headers=new HttpHeaders();
        headers.setBasicAuth(username,password);

        HttpEntity<String> entity=new HttpEntity<>(headers);
        restTemplate.exchange(
                "https://auphonic.com/api/production/" + uuid + "/start.json",
                HttpMethod.POST,
                entity,
                String.class
        );
    }

    public String pollUntilDone(String uuid) throws Exception {

        while(true){
            //Make the api calls
            HttpHeaders headers=new HttpHeaders();
            headers.setBasicAuth(username,password);

            HttpEntity<String> entity = new HttpEntity<>(headers);
            ResponseEntity<String> response = restTemplate.exchange(
                    "https://auphonic.com/api/production/" + uuid + ".json",
                    HttpMethod.GET,
                    entity,
                    String.class
            );

            System.out.println(response.getBody());

            //read the status
            ObjectMapper mapper=new ObjectMapper();
            JsonNode root= mapper.readTree(response.getBody());
            String status=root.path("data").path("status_string").asText();

            //check tha status
            if(status.equals("Done")){
                String downloadUrl=root.path("data").path("output_files").get(0).path("download_url").asText();
                return downloadUrl;
            }
            if(status.equals("Error")){
                String errorMessage = root.path("data").path("error_message").asText();
                throw new Exception("Production failed: " + errorMessage);
            }
            Thread.sleep(3000);
        }
    }
    public byte[] downloadFile(String downloadUrl){
        HttpHeaders headers=new HttpHeaders();
        headers.setBasicAuth(username,password);

        HttpEntity<String> entity = new HttpEntity<>(headers);
        ResponseEntity<byte[]> response = restTemplate.exchange(
                downloadUrl,
                HttpMethod.GET,
                entity,
                byte[].class  //<- byte array
        );
        return response.getBody();
    }

    public byte[] removeNoise(MultipartFile file) throws Exception{
        Path inputPath = Files.createTempFile("input",".wav");
        Files.write(inputPath, file.getBytes());

        //create output file path
        Path outputPath = Files.createTempFile("output",".wav");

        String scriptPath = new ClassPathResource("denoise.py").getFile().getAbsolutePath();

        //run python script
        ProcessBuilder pb= new ProcessBuilder(
                "python",
                scriptPath,
                inputPath.toString(),
                outputPath.toString()
        );
        pb.start().waitFor();

        //read output files
        byte[] cleanedAudio = Files.readAllBytes(outputPath);

        //delete temp files
        Files.delete(inputPath);
        Files.delete(outputPath);

        return cleanedAudio;
    }


}
